"""compare_plans Skill 測試：各交通方式的結果用假資料，只驗排序與風險判斷。"""
from datetime import datetime

import pytest

from commute_agent.skills import compare_plans as cp
from commute_agent.skills.compare_plans import PARKING_RISK_THRESHOLD, compare_plans

CLASS_START = "2026-09-21T09:00:00+08:00"

COURSE = {"name": "數位IC設計", "day_zh": "星期一", "start_time": "09:00",
          "location": "資訊系館4264", "building": "B501 資訊工程系館"}


@pytest.fixture
def world(monkeypatch):
    """每個模式各給一組結果，時鐘凍結，讓測試只驗決策邏輯。"""
    state = {
        "now": "2026-09-21T08:00:00+08:00",
        "minutes": {"walking": 19, "bicycling": 14, "transit": 19, "driving": 8},
        "extra": {},
    }

    def fake_plan(origin, mode, vehicle, schedule_path=""):
        return {"status": "ok", "course": COURSE, "class_starts_at": CLASS_START,
                "travel_minutes": state["minutes"][mode], "buffer_minutes": 8,
                "is_estimate": False, "parking": None, "bike": None,
                "weather_advice": None, **state["extra"].get(mode, {})}

    monkeypatch.setattr(cp, "plan_departure", fake_plan)
    monkeypatch.setattr(cp, "load_settings",
                        lambda: type("S", (), {"timezone": "Asia/Taipei"})())

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(state["now"])

    monkeypatch.setattr(cp, "datetime", FrozenClock)
    return state


def by_mode(result, mode):
    return next(o for o in result["options"] if o["mode"] == mode)


def test_every_mode_gets_an_option(world):
    result = compare_plans()
    assert [o["mode"] for o in result["options"]] == list(cp.MODES)


def test_latest_departure_is_class_start_minus_travel_and_buffer(world):
    # 步行 19 分 ＋ 緩衝 8 分 → 09:00 減 27 分 = 08:33
    assert by_mode(compare_plans(), "walking")["leave_by"].endswith("08:33:00+08:00")


def test_faster_mode_may_leave_later(world):
    result = compare_plans()
    assert by_mode(result, "driving")["leave_by"] > by_mode(result, "walking")["leave_by"]


def test_fastest_mode_wins_when_nothing_else_differs(world):
    assert compare_plans()["best"]["mode"] == "driving"


def test_no_late_warning_before_the_departure_time(world):
    # 還沒到出發時刻，late_by 自然是 0，不需要特別壓抑
    world["now"] = "2026-09-19T20:00:00+08:00"    # 兩天前的週六晚上
    assert by_mode(compare_plans(), "walking")["risks"] == []


def test_being_past_departure_is_a_risk(world):
    world["now"] = "2026-09-21T08:40:00+08:00"   # 步行最晚 08:33，已超過
    risks = by_mode(compare_plans(), "walking")["risks"]
    assert any("最晚出發" in r for r in risks)


def test_long_journey_warns_even_when_the_class_is_still_hours_away(world):
    # 人在外縣市：路程 7 小時、離上課還有 6.5 小時 —— 已經來不及了。
    # 先前用「離上課未滿 6 小時才算風險」去限制，正好會在這種情況吃掉警告，
    # 而這恰恰是最需要提早知道的時候
    world["now"] = "2026-09-21T02:30:00+08:00"
    world["minutes"] = dict.fromkeys(cp.MODES, 7 * 60)
    option = by_mode(compare_plans(), "transit")
    assert option["late_by"] > 0
    assert any("最晚出發" in r for r in option["risks"])


def test_late_options_rank_below_on_time_ones(world):
    world["now"] = "2026-09-21T08:40:00+08:00"
    # 此時步行與大眾運輸都來不及，機車仍可（最晚 08:44）
    assert compare_plans()["best"]["mode"] == "driving"


def test_low_parking_availability_becomes_a_risk(world):
    world["extra"]["driving"] = {"parking": {"name": "三系館地下機車停車場",
                                             "available": PARKING_RISK_THRESHOLD - 1}}
    risks = by_mode(compare_plans(), "driving")["risks"]
    assert any("可能已滿" in r for r in risks)


def test_ample_parking_is_not_a_risk(world):
    world["extra"]["driving"] = {"parking": {"name": "三系館地下機車停車場",
                                             "available": PARKING_RISK_THRESHOLD + 100}}
    assert by_mode(compare_plans(), "driving")["risks"] == []


def test_weather_advice_is_carried_into_risks(world):
    world["extra"]["bicycling"] = {"weather_advice": "出發時降雨機率 70%，會淋到雨"}
    assert "出發時降雨機率 70%，會淋到雨" in by_mode(compare_plans(), "bicycling")["risks"]


def test_mode_without_a_time_is_flagged_and_never_recommended(world):
    # 附近沒有可借的 YouBike 時，不該假裝騎得成
    world["minutes"]["bicycling"] = None
    result = compare_plans()
    bike = by_mode(result, "bicycling")
    assert bike["leave_by"] is None
    assert any("算不出" in r for r in bike["risks"])
    assert result["best"]["mode"] != "bicycling"


def test_fewer_risks_beats_being_slightly_faster(world):
    # 機車最快但停車場快滿，自行車沒有任何風險時應該勝出
    world["extra"]["driving"] = {"parking": {"name": "某停車場", "available": 5}}
    assert compare_plans()["best"]["mode"] == "bicycling"


def test_bike_breakdown_is_passed_through(world):
    detail = {"from_station": {"name": "長榮高中"}, "to_station": {"name": "大學長榮"}}
    world["extra"]["bicycling"] = {"bike": detail}
    assert by_mode(compare_plans(), "bicycling")["bike"] == detail


def test_weather_of_each_departure_time_is_passed_through(world):
    # 各方案出發時刻不同，天氣要各自帶一份，選方式時才知道那個時間點熱不熱、會不會下雨
    hot = {"weather": "晴", "rain_probability": 10, "will_rain": False,
           "temperature": "34", "apparent_temperature": "38"}
    world["extra"]["walking"] = {"weather": hot}
    result = compare_plans()
    assert by_mode(result, "walking")["weather"] == hot
    assert by_mode(result, "transit")["weather"] is None


def test_no_class_is_propagated(world, monkeypatch):
    monkeypatch.setattr(cp, "plan_departure",
                        lambda o, m, v, p="": {"status": "no_class", "note": "課表裡沒有課"})
    assert compare_plans()["status"] == "no_class"


def test_error_is_propagated(world, monkeypatch):
    monkeypatch.setattr(cp, "plan_departure",
                        lambda o, m, v, p="": {"status": "error",
                                            "error_message": "找不到課表檔案"})
    result = compare_plans()
    assert result["status"] == "error"
    assert result["options"] == []
