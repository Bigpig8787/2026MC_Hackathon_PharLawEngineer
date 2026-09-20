"""scenario 測試：情境只在明確啟用時才覆寫，而且只綁在當次請求。"""
import inspect
import threading

import pytest

from commute_agent import scenario
from commute_agent.tools.youbike import get_bike_status


def make(kind, result):
    @scenario.simulated(kind)
    def tool(*args, **kwargs):
        return dict(result)
    return tool


def test_parse_names_keeps_known_names_in_order_without_duplicates():
    assert scenario.parse_names("bike_zero, heavy_rain,bogus,bike_zero") == ["bike_zero", "heavy_rain"]


def test_parse_names_of_nothing_is_empty():
    assert scenario.parse_names(None) == []
    assert scenario.parse_names("") == []


def test_use_activates_and_then_restores():
    assert scenario.active() == frozenset()
    with scenario.use(["heavy_rain"]):
        assert scenario.active() == {"heavy_rain"}
    assert scenario.active() == frozenset()


def test_use_restores_even_when_the_block_raises():
    with pytest.raises(RuntimeError):
        with scenario.use(["heavy_rain"]):
            raise RuntimeError("boom")
    assert scenario.active() == frozenset()


def test_use_ignores_unknown_names():
    with scenario.use(["heavy_rain", "made_up"]):
        assert scenario.active() == {"heavy_rain"}


def test_without_a_scenario_the_tool_result_is_untouched():
    tool = make("weather", {"status": "error", "error_message": "boom"})
    assert tool() == {"status": "error", "error_message": "boom"}


def test_weather_overlay_forces_heavy_rain_and_marks_it_simulated():
    tool = make("weather", {"status": "error", "error_message": "boom", "district": "東區"})
    with scenario.use(["heavy_rain"]):
        result = tool()
    assert result["status"] == "ok"
    assert result["rain_probability"] == 90 and result["will_rain"] is True
    assert result["simulated"] is True
    assert result["district"] == "東區"            # 其餘欄位仍是真的
    assert "error_message" not in result


def test_a_scenario_only_touches_its_own_kind_of_data():
    weather = make("weather", {"status": "ok", "rain_probability": 10})
    with scenario.use(["bike_zero"]):
        assert weather()["rain_probability"] == 10


def test_bike_overlay_removes_every_station_and_keeps_the_need():
    tool = make("bikes", {"status": "ok", "need": "dock", "place_name": "資訊系館",
                          "stations": [{"name": "站A", "docks": 5}]})
    with scenario.use(["bike_zero"]):
        result = tool()
    assert result["status"] == "not_found"
    assert result["stations"] == []
    assert result["need"] == "dock" and result["place_name"] == "資訊系館"
    assert "還不了車" in result["note"] and result["simulated"] is True


def test_parking_overlay_empties_every_lot_but_keeps_their_names():
    tool = make("parking", {"status": "ok", "lots": [{"name": "甲", "available": 300},
                                                     {"name": "乙", "available": 80}]})
    with scenario.use(["parking_full"]):
        lots = tool()["lots"]
    assert [(lot["name"], lot["available"]) for lot in lots] == [("甲", 0), ("乙", 0)]


def test_bus_overlay_clears_arrivals_even_when_the_real_query_failed():
    tool = make("bus", {"status": "error", "error_message": "未設定 TDX", "arrivals": []})
    with scenario.use(["bus_down"]):
        result = tool()
    assert result["status"] == "not_found"
    assert result["arrivals"] == []
    assert "error_message" not in result


def test_rain_observation_overlay_reports_a_downpour():
    tool = make("rain_now", {"status": "ok", "is_raining": False, "level": "none"})
    with scenario.use(["heavy_rain"]):
        result = tool()
    assert result["is_raining"] is True and result["level"] == "heavy"
    assert result["simulated"] is True


def test_wrapper_keeps_the_signature_and_docs_adk_relies_on():
    assert list(inspect.signature(get_bike_status).parameters) == ["place", "need"]
    assert get_bike_status.__name__ == "get_bike_status"
    assert get_bike_status.__doc__


def test_a_scenario_does_not_leak_into_another_thread():
    # 每個請求跑在自己的執行緒：一個使用者開的模擬，不能讓另一個人的請求也看到
    seen = []
    with scenario.use(["heavy_rain"]):
        thread = threading.Thread(target=lambda: seen.append(scenario.active()))
        thread.start()
        thread.join()
    assert seen == [frozenset()]
