"""geocode 測試：兩個來源都用假資料，不打網路也不花錢。"""
import pytest

from commute_agent.tools import geocode

LIBRARY = {"status": "ok", "name": "G001 圖書館(舊)",
           "lat": 22.995525782871347, "lon": 120.21955682352767}
MISSING = {"status": "not_found", "name": "", "lat": None, "lon": None}

GOOGLE_OK = {"status": "OK", "results": [{
    "formatted_address": "701台灣臺南市東區某路一段1號",
    "geometry": {"location": {"lat": 22.9873692, "lng": 120.2204914}}}]}


@pytest.fixture(autouse=True)
def clear_cache():
    geocode._cache.clear()
    yield
    geocode._cache.clear()


@pytest.fixture
def sources(monkeypatch):
    """回傳一個 dict，測試可以自由設定 GIS 認得哪些地點、Google 被呼叫幾次。"""
    state = {"gis": {}, "google_calls": 0, "google": {"status": "not_found",
                                                      "lat": None, "lon": None,
                                                      "name": "", "source": "google"}}

    def fake_google(place):
        state["google_calls"] += 1
        return state["google"]

    monkeypatch.setattr(geocode, "resolve_place",
                        lambda p: state["gis"].get(p, MISSING))
    monkeypatch.setattr(geocode, "_by_google", fake_google)
    return state


def test_google_payload_is_parsed():
    found = geocode.parse_geocode(GOOGLE_OK)
    assert found["lat"] == pytest.approx(22.9873692)
    assert found["lon"] == pytest.approx(120.2204914)


def test_zero_results_is_none():
    assert geocode.parse_geocode({"status": "ZERO_RESULTS", "results": []}) is None


def test_non_ok_status_is_none():
    assert geocode.parse_geocode({"status": "REQUEST_DENIED"}) is None


def test_result_without_location_is_none():
    assert geocode.parse_geocode({"status": "OK", "results": [{"geometry": {}}]}) is None


def test_campus_place_uses_gis_and_does_not_call_google(sources):
    sources["gis"]["圖書館"] = LIBRARY
    found = geocode.geocode_place("圖書館")
    assert found["source"] == "ncku_gis"
    assert sources["google_calls"] == 0


def test_off_campus_address_falls_back_to_google(sources):
    # 截圖裡的問題：住家地址 GIS 查不到，導致 YouBike 借車欄整個失效
    sources["google"] = {"status": "ok", "lat": 22.98, "lon": 120.22,
                         "name": "某路一段1號", "source": "google"}
    found = geocode.geocode_place("台南市東區某路一段1號")
    assert found["status"] == "ok"
    assert found["source"] == "google"
    assert sources["google_calls"] == 1


def test_successful_lookup_is_cached(sources):
    # 地址不會移動，查一次就好，重複查不該再花錢
    sources["google"] = {"status": "ok", "lat": 22.98, "lon": 120.22,
                         "name": "某路", "source": "google"}
    for _ in range(3):
        geocode.geocode_place("台南市東區某路一段1號")
    assert sources["google_calls"] == 1


def test_failed_lookup_is_not_cached(sources):
    # 查不到可能只是暫時的網路問題，不該永久記住失敗
    for _ in range(2):
        geocode.geocode_place("火星基地")
    assert sources["google_calls"] == 2


def test_both_sources_failing_reports_not_found(sources):
    assert geocode.geocode_place("火星基地")["status"] == "not_found"


def test_empty_place_is_rejected_without_any_lookup(sources):
    assert geocode.geocode_place("  ")["status"] == "error"
    assert sources["google_calls"] == 0


def test_missing_key_is_reported_without_calling_the_api(monkeypatch):
    monkeypatch.setattr(geocode, "load_settings",
                        lambda: type("S", (), {"google_maps_api_key": "",
                                               "http_timeout_seconds": 8.0})())
    monkeypatch.setattr(geocode.requests, "get", lambda *a, **k:
                        pytest.fail("沒有金鑰時不該呼叫 API"))
    found = geocode._by_google("某地址")
    assert found["status"] == "not_found"
    assert "GOOGLE_MAPS_API_KEY" in found["error_message"]
