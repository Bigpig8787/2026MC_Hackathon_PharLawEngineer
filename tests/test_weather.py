"""weather 測試：解析是純函式，不打網路也不需要金鑰。"""
import ssl
from datetime import datetime

import pytest
import requests

from commute_agent.tools import weather
from commute_agent.tools.weather import (
    RAIN_ALERT_THRESHOLD,
    SchemaError,
    element_value_at,
    parse_forecast,
)


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def ranged(name: str, key: str, slots: list[tuple[str, str, str]]) -> dict:
    return {"ElementName": name,
            "Time": [{"StartTime": s, "EndTime": e, "ElementValue": [{key: v}]}
                     for s, e, v in slots]}


def location(*elements: dict) -> dict:
    return {"LocationName": "東區", "WeatherElement": list(elements)}


SLOTS = [("2026-09-21T06:00:00+08:00", "2026-09-21T09:00:00+08:00", "10"),
         ("2026-09-21T09:00:00+08:00", "2026-09-21T12:00:00+08:00", "80")]


def test_value_is_taken_from_the_slot_covering_the_moment():
    element = ranged("3小時降雨機率", "ProbabilityOfPrecipitation", SLOTS)
    assert element_value_at(element, at("2026-09-21T07:30:00+08:00"))[
        "ProbabilityOfPrecipitation"] == "10"
    assert element_value_at(element, at("2026-09-21T10:00:00+08:00"))[
        "ProbabilityOfPrecipitation"] == "80"


def test_slot_boundary_belongs_to_the_later_slot():
    element = ranged("3小時降雨機率", "ProbabilityOfPrecipitation", SLOTS)
    assert element_value_at(element, at("2026-09-21T09:00:00+08:00"))[
        "ProbabilityOfPrecipitation"] == "80"


def test_moment_outside_every_slot_has_no_value():
    element = ranged("3小時降雨機率", "ProbabilityOfPrecipitation", SLOTS)
    assert element_value_at(element, at("2026-09-20T00:00:00+08:00")) is None


def test_single_timestamp_elements_use_the_latest_not_later_than_now():
    element = {"ElementName": "溫度", "Time": [
        {"DataTime": "2026-09-21T07:00:00+08:00", "ElementValue": [{"Temperature": "25"}]},
        {"DataTime": "2026-09-21T08:00:00+08:00", "ElementValue": [{"Temperature": "27"}]},
        {"DataTime": "2026-09-21T09:00:00+08:00", "ElementValue": [{"Temperature": "29"}]}]}
    assert element_value_at(element, at("2026-09-21T08:30:00+08:00"))["Temperature"] == "27"


def test_forecast_flags_rain_above_threshold():
    loc = location(ranged("3小時降雨機率", "ProbabilityOfPrecipitation", SLOTS),
                   ranged("天氣現象", "Weather", [(SLOTS[1][0], SLOTS[1][1], "短暫陣雨")]))
    forecast = parse_forecast(loc, at("2026-09-21T10:00:00+08:00"))
    assert forecast["rain_probability"] == 80
    assert forecast["will_rain"] is True
    assert forecast["weather"] == "短暫陣雨"


def test_forecast_does_not_flag_rain_below_threshold():
    loc = location(ranged("3小時降雨機率", "ProbabilityOfPrecipitation", SLOTS))
    assert parse_forecast(loc, at("2026-09-21T07:00:00+08:00"))["will_rain"] is False


def test_exactly_at_threshold_counts_as_rain():
    slots = [("2026-09-21T06:00:00+08:00", "2026-09-21T09:00:00+08:00",
              str(RAIN_ALERT_THRESHOLD))]
    loc = location(ranged("3小時降雨機率", "ProbabilityOfPrecipitation", slots))
    assert parse_forecast(loc, at("2026-09-21T07:00:00+08:00"))["will_rain"] is True


def test_missing_probability_is_none_not_zero():
    # 沒有資料跟「不會下雨」是兩回事，不能混為一談
    loc = location(ranged("天氣現象", "Weather", [(SLOTS[0][0], SLOTS[0][1], "晴")]))
    forecast = parse_forecast(loc, at("2026-09-21T07:00:00+08:00"))
    assert forecast["rain_probability"] is None
    assert forecast["will_rain"] is False


def test_dash_placeholder_is_treated_as_missing():
    slots = [("2026-09-21T06:00:00+08:00", "2026-09-21T09:00:00+08:00", "-")]
    loc = location(ranged("3小時降雨機率", "ProbabilityOfPrecipitation", slots))
    assert parse_forecast(loc, at("2026-09-21T07:00:00+08:00"))["rain_probability"] is None


def test_location_without_elements_is_an_error():
    with pytest.raises(SchemaError):
        parse_forecast({"LocationName": "東區", "WeatherElement": []},
                       at("2026-09-21T07:00:00+08:00"))


# ---- SSL 連線：一般連線優先，被憑證嚴格檢查擋下才換放寬版 ----


class FakeResponse:
    status_code = 200

    def __init__(self, payload=None):
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    """記錄有沒有被建立、掛了哪個 adapter，並回傳預先設定好的結果或例外。"""
    created = 0
    mounted = []
    outcome = FakeResponse()

    def __init__(self):
        type(self).created += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def mount(self, prefix, adapter):
        type(self).mounted.append((prefix, adapter))

    def get(self, url, **kwargs):
        if isinstance(type(self).outcome, Exception):
            raise type(self).outcome
        return type(self).outcome


@pytest.fixture
def fake_session(monkeypatch):
    FakeSession.created = 0
    FakeSession.mounted = []
    FakeSession.outcome = FakeResponse()
    monkeypatch.setattr(weather.requests, "Session", FakeSession)
    return FakeSession


def raises(exc):
    def _get(*args, **kwargs):
        raise exc
    return _get


def test_relaxed_adapter_drops_only_the_strict_flag():
    adapter = weather._RelaxedStrictAdapter()
    context = adapter.poolmanager.connection_pool_kw["ssl_context"]
    assert not context.verify_flags & ssl.VERIFY_X509_STRICT
    # 憑證鏈與主機名稱仍然要驗，不是整個關掉 SSL 驗證
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_normal_connection_is_used_first_and_no_fallback_on_success(monkeypatch, fake_session):
    ok = FakeResponse()
    monkeypatch.setattr(weather.requests, "get", lambda url, **kw: ok)
    assert weather._get_with_ssl_fallback("https://example.test") is ok
    assert fake_session.created == 0


def test_ssl_error_falls_back_to_the_relaxed_session(monkeypatch, fake_session):
    monkeypatch.setattr(weather.requests, "get", raises(requests.exceptions.SSLError("strict")))
    fallback = FakeResponse()
    fake_session.outcome = fallback

    assert weather._get_with_ssl_fallback("https://example.test") is fallback
    assert fake_session.created == 1
    prefix, adapter = fake_session.mounted[0]
    assert prefix == "https://"
    assert isinstance(adapter, weather._RelaxedStrictAdapter)


def test_timeout_is_not_retried_with_the_relaxed_session(monkeypatch, fake_session):
    monkeypatch.setattr(weather.requests, "get", raises(requests.Timeout("slow")))
    with pytest.raises(requests.Timeout):
        weather._get_with_ssl_fallback("https://example.test")
    assert fake_session.created == 0


def _settings():
    return type("S", (), {"cwa_api_key": "test-key", "timezone": "Asia/Taipei",
                          "http_timeout_seconds": 8})()


def test_get_weather_succeeds_through_the_fallback(monkeypatch, fake_session):
    monkeypatch.setattr(weather, "load_settings", _settings)
    monkeypatch.setattr(weather.requests, "get", raises(requests.exceptions.SSLError("strict")))
    loc = location(ranged("3小時降雨機率", "ProbabilityOfPrecipitation", SLOTS))
    fake_session.outcome = FakeResponse({"records": {"Locations": [{"Location": [loc]}]}})

    result = weather.get_weather(when_iso="2026-09-21T10:00:00+08:00")

    assert result["status"] == "ok"
    assert result["rain_probability"] == 80


def test_get_weather_reports_the_error_when_the_fallback_also_fails(monkeypatch, fake_session):
    monkeypatch.setattr(weather, "load_settings", _settings)
    monkeypatch.setattr(weather.requests, "get", raises(requests.exceptions.SSLError("strict")))
    fake_session.outcome = requests.exceptions.SSLError("still bad cert")

    result = weather.get_weather(when_iso="2026-09-21T10:00:00+08:00")

    assert result["status"] == "error"
    assert "SSLError" in result["error_message"]
