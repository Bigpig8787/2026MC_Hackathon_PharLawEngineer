"""weather 測試：解析是純函式，不打網路也不需要金鑰。"""
from datetime import datetime

import pytest

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
