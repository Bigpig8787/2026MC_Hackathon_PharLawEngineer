"""replan 測試：判斷全是純函式，資料與時鐘都由測試指定，不打任何網路。"""
from datetime import datetime

import pytest

from commute_agent import scenario
from commute_agent.skills import replan as rp
from commute_agent.skills.compare_plans import MODES, build_option

NOW = datetime.fromisoformat("2026-09-21T08:00:00+08:00")
CLASS_START = "2026-09-21T09:00:00+08:00"
LABELS = {"walking": "步行", "bicycling": "自行車", "transit": "大眾運輸", "driving": "機車／開車"}
NO_EXTRAS = {"rain_now": None, "bus": None, "scenarios": []}

RAIN = ("rain", "出發時降雨機率 70%，會淋到雨")
PARKING = ("parking_low", "停車場只剩 20 位")


def opt(mode, minutes=10, risks=(), note="", leave_by="2026-09-21T08:40:00+08:00", late_by=0):
    """一筆比較選項，欄位與 compare_plans.build_option 的輸出一致。"""
    return {"mode": mode, "label": LABELS[mode], "minutes": minutes,
            "leave_by": leave_by if minutes is not None else None,
            "late_by": late_by if minutes is not None else None,
            "risks": [text for _, text in risks], "risk_codes": [code for code, _ in risks],
            "note": note}


def decide(previous, options, extras=NO_EXTRAS):
    return rp.decide(previous, options, extras, NOW)


# ---- 決策 ----

def test_first_recommendation_prefers_fewest_risks_then_speed():
    result = decide(None, [opt("walking", 15, [RAIN]), opt("bicycling", 12),
                           opt("transit", 20), opt("driving", 8, [PARKING])])
    assert result["action"] == "init"
    assert result["mode"] == "bicycling"        # 沒有風險的裡面最快


def test_keep_is_the_decision_when_nothing_is_wrong_with_the_current_mode():
    # 兩者都沒有風險：不能只因為別的方式快 2 分鐘就換，那是使用者自己的選擇
    result = decide("walking", [opt("walking", 10), opt("transit", 8)])
    assert result["action"] == "keep"
    assert result["mode"] == "walking"


def test_hard_failure_forces_a_switch_and_says_why():
    result = decide("bicycling", [
        opt("walking", 15), opt("bicycling", None, [("no_time", "算不出路程時間")],
                                note="「成大圖書館」附近沒有借得到車的 YouBike 站"),
        opt("transit", 12), opt("driving", 9)])
    assert result["action"] == "switch"
    assert result["mode"] == "driving"           # 剩下可行的裡最快
    assert "沒有借得到車的 YouBike 站" in result["reasons"][0]
    assert "現在不可行" in result["summary"] and "已改為機車／開車" in result["summary"]


def test_boilerplate_prefix_is_trimmed_from_the_reason():
    # plan_departure 的說明固定以「算不出路程時間，因此無法推算出發時刻。」開頭，
    # 轉述給使用者時只留具體原因，不要每句都重複這句
    note = "算不出路程時間，因此無法推算出發時刻。「成大圖書館」附近沒有借得到車的 YouBike 站"
    result = decide("bicycling", [
        opt("bicycling", None, [("no_time", "算不出路程時間")], note=note), opt("walking", 15)])
    assert result["reasons"] == ["「成大圖書館」附近沒有借得到車的 YouBike 站"]
    assert "算不出路程時間，因此" not in result["summary"]


def test_a_note_that_is_only_boilerplate_falls_back_to_the_generic_reason():
    result = decide("bicycling", [
        opt("bicycling", None, [("no_time", "算不出路程時間")],
            note="算不出路程時間，因此無法推算出發時刻。"), opt("walking", 15)])
    assert result["reasons"] == ["算不出路程時間"]


def test_reasons_that_already_end_with_a_period_are_joined_cleanly():
    # 天氣建議本身以「。」結尾；串接多個原因時不能出現「。；」
    rain = ("rain", "出發時降雨機率 90%，會淋到雨，可考慮改搭公車。")
    raining = ("raining_now", "目前成功雨量站正在下雨（過去 10 分鐘 4 mm）")
    result = decide("walking", [opt("walking", 10, [rain, raining]), opt("transit", 15)])
    assert result["action"] == "switch"
    assert "。；" not in result["summary"]
    assert "可考慮改搭公車；目前成功雨量站" in result["summary"]


def test_being_late_is_a_hard_failure_too():
    result = decide("walking", [
        opt("walking", 40, [("late", "已經超過最晚出發時間 5 分鐘")], late_by=5),
        opt("driving", 10)])
    assert result["action"] == "switch" and result["mode"] == "driving"
    assert result["reason_codes"] == ["late"]


def test_soft_risk_switches_when_the_alternative_is_clearly_better():
    result = decide("walking", [opt("walking", 10, [RAIN]), opt("transit", 15)])
    assert result["action"] == "switch"
    assert result["mode"] == "transit"
    assert "有風險" in result["summary"] and result["reason_codes"] == ["rain"]


def test_soft_risk_alone_does_not_justify_a_much_slower_alternative():
    # 慢了 15 分鐘（超過 10 分鐘的容忍）：為了不淋雨多花這麼久不划算，維持並提醒
    result = decide("walking", [opt("walking", 10, [RAIN]), opt("transit", 25)])
    assert result["action"] == "keep"
    assert "留意" in result["summary"] and "沒有更好的替代方案" in result["summary"]


def test_equal_risk_never_causes_a_flip():
    # 降雨機率在門檻上下跳時最怕來回切換：兩邊風險一樣多就不動
    result = decide("walking", [opt("walking", 10, [RAIN]), opt("bicycling", 8, [RAIN])])
    assert result["action"] == "keep"


def test_no_viable_mode_says_so_instead_of_pretending():
    hard = [("late", "已經超過最晚出發時間 9 分鐘")]
    result = decide("walking", [opt(m, 30, hard, late_by=9) for m in MODES])
    assert result["action"] == "no_option"
    assert result["mode"] == "walking"           # 沒得選就不動使用者的選擇
    assert "所有交通方式" in result["summary"] and "告知老師" in result["summary"]


def test_transit_without_service_is_not_viable():
    extras = {**NO_EXTRAS, "bus": {"status": "not_found", "note": "附近站牌目前沒有班次"}}
    result = decide(None, [opt("walking", 20), opt("transit", 6)], extras)
    assert result["mode"] == "walking"
    transit = next(o for o in result["options"] if o["mode"] == "transit")
    assert transit["viable"] is False and "沒有班次" in transit["hard"][0]


def test_a_bus_lookup_that_errored_is_unknown_not_a_failure():
    extras = {**NO_EXTRAS, "bus": {"status": "error", "error_message": "未設定 TDX"}}
    assert decide(None, [opt("walking", 20), opt("transit", 6)], extras)["mode"] == "transit"


def test_result_carries_what_the_ui_and_next_round_need():
    result = decide("walking", [opt("walking", 10, [RAIN]), opt("transit", 15)])
    assert result["facts"]["minutes"] == 15
    assert result["soft_codes"] == []            # 換過去的公車沒有軟風險
    assert {o["mode"] for o in result["options"]} == {"walking", "transit"}
    assert result["at"] == "2026-09-21T08:00:00+08:00"


# ---- 即時降雨觀測 ----

RAINING = {"status": "ok", "is_raining": True, "past10min_mm": 2.5,
           "station": {"name": "成功"}}


def test_raining_now_is_a_soft_risk_for_exposed_modes_leaving_soon():
    _, soft = rp.assess(opt("walking"), {**NO_EXTRAS, "rain_now": RAINING}, NOW)
    assert [code for code, _ in soft] == ["raining_now"]
    assert "成功雨量站" in soft[0][1] and "2.5 mm" in soft[0][1]


def test_raining_now_does_not_affect_transit():
    _, soft = rp.assess(opt("transit"), {**NO_EXTRAS, "rain_now": RAINING}, NOW)
    assert soft == []


def test_raining_now_ignored_when_leaving_is_hours_away():
    far = opt("walking", leave_by="2026-09-21T12:00:00+08:00")
    assert rp.assess(far, {**NO_EXTRAS, "rain_now": RAINING}, NOW)[1] == []


def test_dry_reading_adds_no_risk():
    dry = {"status": "ok", "is_raining": False, "station": {"name": "成功"}}
    assert rp.assess(opt("walking"), {**NO_EXTRAS, "rain_now": dry}, NOW)[1] == []


# ---- replan：快速檢查與完整比較 ----

CLASS_STARTS = datetime.fromisoformat(CLASS_START)


class World:
    """假的 plan_departure／compare_plans／即時觀測，並記錄各自被呼叫幾次。"""

    def __init__(self):
        self.minutes = {"walking": 10, "bicycling": 12, "transit": 15, "driving": 8}
        self.extra = {}
        self.calls = {"plan": 0, "compare": 0, "rain": 0, "bus": 0}
        self.rain = {"status": "ok", "is_raining": False, "station": {"name": "成功"}}
        self.bus = {"status": "ok", "arrivals": [{"route": "5"}]}

    def plan(self, origin, mode, vehicle, path, now=None):
        self.calls["plan"] += 1
        return {"status": "ok", "course": {"name": "課"}, "class_starts_at": CLASS_START,
                "travel_minutes": self.minutes[mode], "buffer_minutes": 8,
                "is_estimate": False, "parking": None, "bike": None, "weather": None,
                "weather_advice": None, "note": "", **self.extra.get(mode, {})}

    def compare(self, origin, vehicle, path, now=None):
        self.calls["compare"] += 1
        return {"status": "ok", "options": [
            build_option(m, self.plan(origin, m, vehicle, path, now), now, CLASS_STARTS)
            for m in MODES]}

    def observe_rain(self):
        self.calls["rain"] += 1
        return self.rain

    def observe_bus(self, place):
        self.calls["bus"] += 1
        return self.bus

    def replan(self, previous="walking", **kwargs):
        return rp.replan("成大圖書館", "機車", "", previous, now=NOW,
                         plan_fn=self.plan, compare_fn=self.compare,
                         bus_fn=self.observe_bus, rain_fn=self.observe_rain, **kwargs)


@pytest.fixture
def world():
    return World()


def test_healthy_current_mode_is_checked_alone_without_comparing_everything(world):
    result = world.replan("walking")
    assert result["action"] == "keep" and result["checked"] == "quick"
    assert world.calls["compare"] == 0            # 省下四種路線查詢（計費）


def test_hard_failure_triggers_the_full_comparison(world):
    world.minutes["bicycling"] = None
    result = world.replan("bicycling")
    assert result["checked"] == "full" and world.calls["compare"] == 1
    assert result["action"] == "switch" and result["mode"] != "bicycling"


def test_a_new_soft_risk_triggers_the_full_comparison(world):
    world.extra["walking"] = {"weather_advice": RAIN[1]}
    world.replan("walking")
    assert world.calls["compare"] == 1


def test_an_already_accepted_soft_risk_does_not_recompute_every_round(world):
    world.extra["walking"] = {"weather_advice": RAIN[1]}
    result = world.replan("walking", known_soft={"rain"})
    assert world.calls["compare"] == 0
    assert result["action"] == "keep" and result["soft_codes"] == ["rain"]


def test_a_different_new_risk_still_gets_noticed(world):
    world.extra["walking"] = {"weather_advice": RAIN[1]}
    world.replan("walking", known_soft={"parking_low"})
    assert world.calls["compare"] == 1


def test_first_call_without_a_previous_mode_recommends(world):
    result = world.replan(None)
    assert result["action"] == "init" and world.calls["compare"] == 1


def test_unknown_previous_mode_is_treated_as_first_call(world):
    assert world.replan("teleport")["action"] == "init"


def test_a_plan_that_cannot_be_made_is_passed_through(world):
    world.plan = lambda *a, **k: {"status": "no_class", "note": "課表裡沒有課"}
    result = world.replan("walking")
    assert result["status"] == "no_class"


def test_a_failed_comparison_is_passed_through(world):
    world.compare = lambda *a, **k: {"status": "error", "error_message": "找不到課表"}
    assert world.replan(None)["status"] == "error"


# ---- 模擬時間下的即時觀測 ----

def test_real_time_uses_live_observations(world):
    world.replan("walking", simulated=False)
    assert world.calls["rain"] == 1


def test_simulated_time_ignores_live_observations(world):
    # 模擬的週一早上八點，去看「真實現在」的雨量或公車，是拿錯時間的資料做判斷
    world.replan("walking", simulated=True)
    world.replan("transit", simulated=True)
    assert world.calls["rain"] == 0 and world.calls["bus"] == 0


def test_a_rain_scenario_makes_the_observation_count_even_in_simulated_time(world):
    world.rain = RAINING
    with scenario.use(["heavy_rain"]):
        result = world.replan("walking", simulated=True)
    assert world.calls["rain"] == 1
    assert result["checked"] == "full"            # 出現新的軟風險
    assert result["simulated_scenarios"] == ["heavy_rain"]


def test_a_bus_outage_scenario_makes_the_current_transit_ride_unviable(world):
    world.bus = {"status": "not_found", "note": "（模擬）公車停駛"}
    with scenario.use(["bus_down"]):
        result = world.replan("transit", simulated=True)
    assert world.calls["bus"] >= 1
    assert result["action"] == "switch" and result["mode"] != "transit"
    assert "公車停駛" in result["summary"]


# ---- 給 Agent 用的入口 ----

def test_agent_entry_needs_an_origin(monkeypatch):
    monkeypatch.setattr(rp, "load_settings", lambda: type("S", (), {"default_origin": ""})())
    assert rp.replan_commute()["status"] == "error"


def test_agent_entry_falls_back_to_the_default_origin(monkeypatch):
    seen = {}
    monkeypatch.setattr(rp, "load_settings", lambda: type("S", (), {"default_origin": "住家"})())
    monkeypatch.setattr(rp, "replan", lambda origin, vehicle, path, prev: seen.update(
        origin=origin, prev=prev) or {"status": "ok"})
    rp.replan_commute(previous_mode="walking")
    assert seen == {"origin": "住家", "prev": "walking"}
