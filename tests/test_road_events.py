"""road_events Tool 測試。

fixture 模式讀的 commute_agent/fixtures/ncku_traffic/Tainan.json 是手寫示範資料，
不是真實錄製（該資料夾還沒有 TDX 金鑰可以錄，見資料夾裡的 README）。
live 模式的測試全部用假的 requests.get/post，不代表真實 TDX 回應欄位一定長這樣。
"""
import pytest
import requests

from commute_agent.tools import road_events

TAIPEI_TOKEN_BODY = {"access_token": "fake-token-1", "expires_in": 3600, "token_type": "bearer"}

# 成功校區附近，用來對 fixtures/ncku_traffic/Tainan.json 的三筆事件算距離：
# 事件一（小東路）約 200m 內、事件二（大學路）約 350m、事件三（中華東路）約 2.5km
NCKU_LAT, NCKU_LON = 22.9997, 120.2220


class FakeResponse:
    def __init__(self, payload=None, status_code=200, bad_json=False):
        self._payload, self.status_code, self._bad = payload, status_code, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("PROVIDER_MODE", "live")
    monkeypatch.setenv("TDX_CLIENT_ID", "test-id")
    monkeypatch.setenv("TDX_CLIENT_SECRET", "test-secret")


@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("PROVIDER_MODE", "fixture")


@pytest.fixture(autouse=True)
def clean_token_cache():
    road_events.reset_token_cache()
    yield
    road_events.reset_token_cache()


# ---------- access token ----------

def test_get_access_token_returns_token_from_response(monkeypatch):
    monkeypatch.setattr(road_events.requests, "post", lambda *a, **k: FakeResponse(TAIPEI_TOKEN_BODY))
    token = road_events.get_access_token("id", "secret", timeout=5)
    assert token == "fake-token-1"


def test_get_access_token_is_cached_within_expiry(monkeypatch):
    calls = []
    monkeypatch.setattr(road_events.requests, "post",
                        lambda *a, **k: calls.append(1) or FakeResponse(TAIPEI_TOKEN_BODY))
    road_events.get_access_token("id", "secret", timeout=5, now=1_000_000.0)
    road_events.get_access_token("id", "secret", timeout=5, now=1_000_100.0)
    assert len(calls) == 1


def test_get_access_token_refetches_after_expiry(monkeypatch):
    calls = []
    monkeypatch.setattr(road_events.requests, "post",
                        lambda *a, **k: calls.append(1) or FakeResponse(TAIPEI_TOKEN_BODY))
    road_events.get_access_token("id", "secret", timeout=5, now=1_000_000.0)
    # expires_in=3600，快取提前 60 秒視為過期；3600 秒後一定已過期
    road_events.get_access_token("id", "secret", timeout=5, now=1_000_000.0 + 3600)
    assert len(calls) == 2


def test_get_access_token_http_error_raises_token_error(monkeypatch):
    monkeypatch.setattr(road_events.requests, "post", lambda *a, **k: FakeResponse(status_code=401))
    with pytest.raises(road_events.TokenError):
        road_events.get_access_token("id", "bad-secret", timeout=5)


def test_get_access_token_missing_field_raises(monkeypatch):
    monkeypatch.setattr(road_events.requests, "post", lambda *a, **k: FakeResponse({"token_type": "bearer"}))
    with pytest.raises(road_events.TokenError):
        road_events.get_access_token("id", "secret", timeout=5)


def test_get_access_token_network_error_raises(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("dns fail")
    monkeypatch.setattr(road_events.requests, "post", boom)
    with pytest.raises(road_events.TokenError):
        road_events.get_access_token("id", "secret", timeout=5)


# ---------- parse_road_events ----------

def test_parse_handles_nested_position():
    rows = [{"EventID": "E1", "Description": "事故", "RoadName": "小東路",
             "Position": {"PositionLon": 120.22, "PositionLat": 23.0}}]
    events = road_events.parse_road_events(rows)
    assert events == [{
        "event_id": "E1", "description": "事故", "type_code": None,
        "type_is_code": False, "road_name": "小東路", "reported_at": None,
        "lat": 23.0, "lon": 120.22, "raw": rows[0],
    }]


def test_parse_handles_flat_lon_lat_fallback():
    rows = [{"EventID": "E2", "Latitude": 23.0, "Longitude": 120.22}]
    events = road_events.parse_road_events(rows)
    assert events[0]["lat"] == 23.0 and events[0]["lon"] == 120.22


def test_parse_unwraps_dict_with_data_key():
    payload = {"Data": [{"EventID": "E3", "Position": {"PositionLon": 120.22, "PositionLat": 23.0}}]}
    events = road_events.parse_road_events(payload)
    assert len(events) == 1 and events[0]["event_id"] == "E3"


def test_parse_type_is_code_true_when_no_description():
    rows = [{"EventID": "E4", "SubEventType": 9, "Position": {"PositionLon": 120.22, "PositionLat": 23.0}}]
    events = road_events.parse_road_events(rows)
    assert events[0]["type_code"] == 9 and events[0]["type_is_code"] is True


def test_parse_type_is_code_false_when_description_present():
    rows = [{"EventID": "E5", "SubEventType": 9, "Description": "施工",
             "Position": {"PositionLon": 120.22, "PositionLat": 23.0}}]
    events = road_events.parse_road_events(rows)
    assert events[0]["type_is_code"] is False


def test_parse_empty_list_returns_empty():
    assert road_events.parse_road_events([]) == []


def test_parse_missing_coordinates_raises_schema_error_listing_keys():
    rows = [{"EventID": "E6", "Foo": "bar"}]
    with pytest.raises(road_events.SchemaError) as exc:
        road_events.parse_road_events(rows)
    assert "EventID" in str(exc.value) and "Foo" in str(exc.value)


def test_parse_non_list_non_dict_raises():
    with pytest.raises(road_events.SchemaError):
        road_events.parse_road_events("not a list")


def test_parse_dict_without_recognizable_array_raises():
    with pytest.raises(road_events.SchemaError):
        road_events.parse_road_events({"Unexpected": "shape"})


# ---------- get_road_events：fixture 模式 ----------

def test_fixture_mode_filters_by_radius(fixture_mode):
    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON, radius_m=250)
    assert result["status"] == "ok"
    names = [e["road_name"] for e in result["events"]]
    assert names == ["小東路"]  # 只有最近那筆在 250m 內


def test_fixture_mode_wider_radius_includes_more_and_sorts_by_distance(fixture_mode):
    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON, radius_m=1000)
    names = [e["road_name"] for e in result["events"]]
    assert names == ["小東路", "大學路"]
    assert result["events"][0]["distance_m"] <= result["events"][1]["distance_m"]


def test_fixture_mode_missing_city_file_is_error(fixture_mode):
    result = road_events.get_road_events("Taipei", NCKU_LAT, NCKU_LON, radius_m=500)
    assert result["status"] == "error"
    assert "Taipei" in result["error_message"]


def test_fixture_mode_far_event_excluded_with_small_radius(fixture_mode):
    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON, radius_m=100)
    assert result["events"] == []
    assert result["count"] == 0


# ---------- get_road_events：live 模式 ----------

def test_live_mode_sends_bearer_token_and_format_json(live, monkeypatch):
    seen = {}

    def fake_post(url, data=None, **kwargs):
        assert url == road_events.TOKEN_URL
        return FakeResponse(TAIPEI_TOKEN_BODY)

    def fake_get(url, params=None, headers=None, **kwargs):
        seen["url"], seen["params"], seen["headers"] = url, params, headers
        return FakeResponse([{"EventID": "L1", "Description": "測試",
                              "Position": {"PositionLon": NCKU_LON, "PositionLat": NCKU_LAT}}])

    monkeypatch.setattr(road_events.requests, "post", fake_post)
    monkeypatch.setattr(road_events.requests, "get", fake_get)

    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON, radius_m=500)
    assert result["status"] == "ok" and result["count"] == 1
    assert seen["url"] == "https://tdx.transportdata.tw/api/basic/v1/Traffic/RoadEvent/LiveEvent/City/Tainan"
    assert seen["params"] == {"$format": "JSON"}
    assert seen["headers"]["Authorization"] == "Bearer fake-token-1"


def test_live_mode_token_failure_surfaces_as_error(live, monkeypatch):
    monkeypatch.setattr(road_events.requests, "post", lambda *a, **k: FakeResponse(status_code=403))
    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON)
    assert result["status"] == "error" and "error_message" in result


def test_live_mode_401_from_data_endpoint_is_error(live, monkeypatch):
    monkeypatch.setattr(road_events.requests, "post", lambda *a, **k: FakeResponse(TAIPEI_TOKEN_BODY))
    monkeypatch.setattr(road_events.requests, "get", lambda *a, **k: FakeResponse(status_code=401))
    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON)
    assert result["status"] == "error" and "金鑰" in result["error_message"]


def test_live_mode_timeout_is_error(live, monkeypatch):
    monkeypatch.setattr(road_events.requests, "post", lambda *a, **k: FakeResponse(TAIPEI_TOKEN_BODY))

    def timeout(*a, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(road_events.requests, "get", timeout)
    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON)
    assert result["status"] == "error" and "逾時" in result["error_message"]


def test_live_mode_bad_json_is_error(live, monkeypatch):
    monkeypatch.setattr(road_events.requests, "post", lambda *a, **k: FakeResponse(TAIPEI_TOKEN_BODY))
    monkeypatch.setattr(road_events.requests, "get", lambda *a, **k: FakeResponse(bad_json=True))
    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON)
    assert result["status"] == "error"


def test_live_mode_malformed_event_becomes_error_result(live, monkeypatch):
    monkeypatch.setattr(road_events.requests, "post", lambda *a, **k: FakeResponse(TAIPEI_TOKEN_BODY))
    monkeypatch.setattr(road_events.requests, "get", lambda *a, **k: FakeResponse([{"Nothing": "useful"}]))
    result = road_events.get_road_events("Tainan", NCKU_LAT, NCKU_LON)
    assert result["status"] == "error" and "回應格式異常" in result["error_message"]
