"""rain_observation 測試：解析與選站是純函式；網路一律用假的，不需要金鑰。"""
import pytest
import requests

from commute_agent import scenario
from commute_agent.tools import rain_observation as ro


def station(name, lat, lon, now=0.0, past10=0.0, past1h=0.0, county="臺南市"):
    def element(value):
        return {"Precipitation": str(value)}

    return {"StationName": name, "StationId": name,
            "ObsTime": {"DateTime": "2026-09-20T01:10:00+08:00"},
            "GeoInfo": {"CountyName": county, "TownName": "東區", "Coordinates": [
                {"CoordinateName": "TWD67", "StationLatitude": "0", "StationLongitude": "0"},
                {"CoordinateName": "WGS84", "StationLatitude": str(lat),
                 "StationLongitude": str(lon)}]},
            "RainfallElement": {"Now": element(now), "Past10Min": element(past10),
                                "Past1hr": element(past1h)}}


def payload(*stations):
    return {"records": {"Station": list(stations)}}


class FakeResponse:
    def __init__(self, body=None, status_code=200):
        self._body, self.status_code = body, status_code

    def json(self):
        return self._body


# ---- 解析 ----

def test_coordinates_come_from_wgs84_not_twd67():
    parsed = ro.parse_stations(payload(station("成大", 22.9968, 120.2168)))[0]
    assert (parsed["lat"], parsed["lon"]) == (22.9968, 120.2168)


def test_negative_readings_mean_missing_not_zero():
    # 氣象署用 -998 之類的負數表示缺測；當成 0 會把「沒資料」誤報成「沒下雨」
    parsed = ro.parse_stations(payload(station("故障站", 23.0, 120.2, now=-998, past10=-998, past1h=-998)))[0]
    assert parsed["now_mm"] is None and parsed["past10min_mm"] is None
    assert parsed["past1hr_mm"] is None


def test_station_without_coordinates_is_skipped():
    broken = {"StationName": "沒座標", "GeoInfo": {"Coordinates": []}, "RainfallElement": {}}
    assert ro.parse_stations(payload(broken, station("好站", 23.0, 120.2)))[0]["name"] == "好站"


def test_malformed_payload_is_rejected():
    with pytest.raises(ro.RainError):
        ro.parse_stations({"records": {}})


# ---- 選站 ----

def test_nearest_station_wins_and_distance_is_reported():
    stations = ro.parse_stations(payload(station("遠", 23.04, 120.2), station("近", 22.9990, 120.2170)))
    nearest = ro.nearest_stations(stations, ro.NCKU_LAT, ro.NCKU_LON)
    assert [s["name"] for s in nearest] == ["近", "遠"]
    assert nearest[0]["distance_km"] < nearest[1]["distance_km"]


def test_station_without_any_reading_is_not_used():
    dead = station("故障", 22.9969, 120.2169, now=-998, past10=-998)
    ok = station("正常", 23.02, 120.2)
    nearest = ro.nearest_stations(ro.parse_stations(payload(dead, ok)), ro.NCKU_LAT, ro.NCKU_LON)
    assert [s["name"] for s in nearest] == ["正常"]


def test_station_too_far_away_cannot_speak_for_ncku():
    far = station("高雄", 22.6, 120.3)
    assert ro.nearest_stations(ro.parse_stations(payload(far)), ro.NCKU_LAT, ro.NCKU_LON) == []


# ---- 雨勢分級 ----

@pytest.mark.parametrize("now,past10,hour,raining,level", [
    (0.0, 0.0, 0.0, False, "none"),
    (0.5, 0.0, 0.0, True, "light"),
    (0.0, 1.0, 1.0, True, "light"),
    (0.0, 0.0, 2.0, False, "light"),      # 雨剛停：現在沒下，但過去一小時有雨
    (3.0, 4.0, 12.0, True, "heavy"),
    (0.0, 0.0, 12.0, False, "heavy"),     # 雨停了，路面仍濕
    (None, None, None, False, "none"),
])
def test_classification(now, past10, hour, raining, level):
    assert ro.classify(now, past10, hour) == (raining, level)


# ---- 對外的查詢 ----

@pytest.fixture
def api(monkeypatch):
    """假的設定、假的網路、乾淨的快取。回傳可調整的狀態。"""
    state = {"calls": 0, "response": FakeResponse(payload(
        station("成大附近", 22.9990, 120.2170, now=0.0, past10=1.5, past1h=3.0)))}
    monkeypatch.setitem(ro._cache, "stations", [])
    monkeypatch.setitem(ro._cache, "fetched_at", 0.0)
    monkeypatch.setattr(ro, "load_settings", lambda: type(
        "S", (), {"cwa_api_key": "test-key", "http_timeout_seconds": 8})())

    def fake_get(url, **kwargs):
        state["calls"] += 1
        if isinstance(state["response"], Exception):
            raise state["response"]
        return state["response"]

    monkeypatch.setattr(ro, "_get_with_ssl_fallback", fake_get)
    return state


def test_reports_rain_from_the_nearest_station(api):
    result = ro.get_rain_now()
    assert result["status"] == "ok"
    assert result["is_raining"] is True                 # 過去 10 分鐘 1.5 mm
    assert result["level"] == "light"
    assert result["station"]["name"] == "成大附近"
    assert result["past10min_mm"] == 1.5


def test_second_call_uses_the_cache(api):
    ro.get_rain_now()
    ro.get_rain_now()
    assert api["calls"] == 1


def test_missing_key_is_an_error_without_touching_the_network(api, monkeypatch):
    monkeypatch.setattr(ro, "load_settings", lambda: type(
        "S", (), {"cwa_api_key": "", "http_timeout_seconds": 8})())
    assert ro.get_rain_now()["status"] == "error"
    assert api["calls"] == 0


def test_http_error_is_reported(api):
    api["response"] = FakeResponse({}, status_code=500)
    result = ro.get_rain_now()
    assert result["status"] == "error" and "HTTP 500" in result["error_message"]


def test_timeout_and_connection_errors_are_reported(api):
    api["response"] = requests.Timeout()
    assert "逾時" in ro.get_rain_now()["error_message"]
    api["response"] = requests.ConnectionError()
    assert "無法連線" in ro.get_rain_now()["error_message"]


def test_no_station_in_range_is_not_found(api):
    api["response"] = FakeResponse(payload(station("高雄", 22.6, 120.3)))
    assert ro.get_rain_now()["status"] == "not_found"


def test_heavy_rain_scenario_overrides_a_dry_reading(api):
    api["response"] = FakeResponse(payload(station("成大附近", 22.9990, 120.2170)))
    with scenario.use(["heavy_rain"]):
        result = ro.get_rain_now()
    assert result["is_raining"] is True and result["simulated"] is True
    assert result["station"]["name"] == "成大附近"       # 站名等真實資訊保留
