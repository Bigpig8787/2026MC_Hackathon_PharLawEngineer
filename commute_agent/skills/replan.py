"""Skill 層：環境變化後，自己判斷原本的交通方式還行不行，不行就換（Observe → Check → Adapt）。

這是 CampusPulse Agent Loop 裡缺的那一段：compare_plans 會比較各方式、recommend_plan
會選一個，但都是「問一次答一次」。這支負責「持續盯著」：前端每隔一段時間帶著上一輪的
交通方式來問，這裡回答「維持」還是「改」，以及為什麼。

整個判斷是確定性的程式，沒有模型參與，所以可測、可重現、也不吃 Gemini 額度：

- 硬失效（一定要換）：附近借不到車、停車場全滿、會遲到、公車沒班次。
- 軟風險（有更好的才換）：會淋雨、車位偏少。
- 防抖：軟風險要有「風險明顯更少、又不會慢太多」的替代方案才換，
  否則降雨機率在 40% 上下跳一下就換來換去，使用者只會覺得被耍。

省錢是刻意設計的：路線查詢（Google Routes）是計費的，所以每一輪先只檢查「目前這一種」，
沒有問題就直接回「維持」；只有出現硬失效、或出現「之前沒見過的新風險」才把四種全比一遍。
前端把上一輪已經接受的軟風險代碼帶回來（known_soft），同樣的風險就不會每輪重算。

即時觀測（現在有沒有在下雨、公車有沒有班次）只在「真實時間」才有意義：模擬時間下
查到的是「真正的現在」，拿來判斷模擬的早上八點是錯的。所以模擬時間時略過，
除非 Demo 明確啟用了對應的模擬情境（那時覆寫值就是要被採用的）。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from api import load_settings
from commute_agent.scenario import active as active_scenarios
from commute_agent.skills.compare_plans import MODES, build_option, compare_plans
from commute_agent.skills.departure_plan import EXPOSED_MODES, plan_departure
from commute_agent.tools.rain_observation import get_rain_now
from commute_agent.tools.route_link import TRAVEL_MODE_LABELS
from commute_agent.tools.tdx_bus import get_bus_eta

# 這些代碼出現就代表這個方式「現在走不通」，一定要換
HARD_CODES = ("no_time", "late", "no_bus")

# 軟風險的替代方案最多可以比原本慢這麼多分鐘，超過就不值得為了少一點風險多花時間
SWITCH_TOLERANCE_MINUTES = 10

# 最晚出發時刻離現在多近，「現在正在下雨」才算對這一趟有影響
RAIN_NOW_WINDOW_MINUTES = 90

# plan_departure 在算不出路程時，說明前面固定加的一句話；轉述原因時只留後面的具體原因
NO_TIME_BOILERPLATE = "算不出路程時間，因此無法推算出發時刻。"


def _label(mode: str | None) -> str:
    return TRAVEL_MODE_LABELS.get(mode, mode or "")


def _hhmm(iso: str | None) -> str:
    return iso[11:16] if iso else "--:--"


def observe(origin: str, simulated: bool, need_bus: bool,
            bus_fn=get_bus_eta, rain_fn=get_rain_now, extras: dict | None = None) -> dict:
    """蒐集即時觀測。模擬時間下只有被明確模擬的項目才查（見模組說明）。

    傳入先前蒐集的 extras 就只補查缺的：快速檢查升級成完整比較時，
    雨量已經查過一次，不該再打一次氣象署。
    """
    scenarios = active_scenarios()
    if extras is None:
        extras = {"rain_now": None, "bus": None, "scenarios": sorted(scenarios),
                  "fetched": set()}
    fetched = extras["fetched"]
    if "rain" not in fetched and (not simulated or "heavy_rain" in scenarios):
        extras["rain_now"] = rain_fn()
        fetched.add("rain")
    if (need_bus and "bus" not in fetched and origin
            and (not simulated or "bus_down" in scenarios)):
        extras["bus"] = bus_fn(origin)
        fetched.add("bus")
    return extras


def assess(option: dict, extras: dict, now: datetime) -> tuple[list, list]:
    """把一個方案的風險分成 (硬失效, 軟風險)，每項是 (代碼, 說明)。"""
    hard, soft = [], []
    for code, text in zip(option.get("risk_codes", []), option["risks"]):
        if code == "no_time" and option.get("note"):
            # 用更具體的原因取代「算不出路程時間」，並去掉 plan_departure 固定加的樣板前綴
            text = option["note"].removeprefix(NO_TIME_BOILERPLATE).strip() or text
        (hard if code in HARD_CODES else soft).append((code, text))

    bus = extras.get("bus")
    if option["mode"] == "transit" and bus and bus.get("status") == "not_found":
        hard.append(("no_bus", bus.get("note") or "附近站牌目前沒有班次"))

    rain = extras.get("rain_now")
    if (rain and rain.get("status") == "ok" and rain.get("is_raining")
            and option["mode"] in EXPOSED_MODES and option.get("leave_by")):
        leave = datetime.fromisoformat(option["leave_by"])
        if (leave - now).total_seconds() / 60 <= RAIN_NOW_WINDOW_MINUTES:
            station = (rain.get("station") or {}).get("name") or "附近"
            mm = rain.get("past10min_mm")
            detail = f"過去 10 分鐘 {mm:g} mm" if mm is not None else "剛下過雨"
            soft.append(("raining_now", f"目前{station}雨量站正在下雨（{detail}）"))
    return hard, soft


def _rank(assessed: dict) -> tuple:
    # 風險少的優先，其次是快的，最後照 MODES 順序讓結果穩定、不會每次不同
    return (len(assessed["soft"]), assessed["minutes"], MODES.index(assessed["mode"]))


def _compact(assessed: dict) -> dict:
    return {"mode": assessed["mode"], "label": assessed["label"],
            "minutes": assessed["minutes"], "leave_by": assessed["leave_by"],
            "viable": not assessed["hard"],
            "hard": [text for _, text in assessed["hard"]],
            "soft": [text for _, text in assessed["soft"]]}


def _join(texts) -> str:
    """把幾句原因串成一句。各句自己可能已經以「。」結尾，先去掉，才不會出現「。；」。"""
    return "；".join(text.rstrip("。 ") for text in texts)


def _summary(action: str, prev: dict | None, chosen: dict | None, reasons: list[str]) -> str:
    if action == "no_option":
        return f"目前所有交通方式都不可行或會遲到：{_join(reasons)}。建議儘早出發，或事先告知老師。"
    plan = f"約 {chosen['minutes']} 分，最晚 {_hhmm(chosen['leave_by'])} 出發"
    if action == "switch":
        state = "現在不可行" if prev["hard"] else "有風險"
        return f"{prev['label']}{state}（{_join(reasons)}），已改為{chosen['label']}：{plan}。"
    if action == "init":
        return f"建議{chosen['label']}：{plan}。"
    tail = ""
    if chosen["soft"]:
        tail = f"留意：{_join(text for _, text in chosen['soft'])}（目前沒有更好的替代方案）。"
    return f"{chosen['label']}目前可行：{plan}。{tail}"


def decide(previous_mode: str | None, options: list[dict], extras: dict,
           now: datetime, checked: str = "full") -> dict:
    """依各方案的風險，決定維持、改換或初次建議。純函式：所有資料都由呼叫端給。"""
    assessed = {}
    for option in options:
        hard, soft = assess(option, extras, now)
        assessed[option["mode"]] = {**option, "hard": hard, "soft": soft}
    ordered = [assessed[m] for m in MODES if m in assessed]
    viable = sorted((a for a in ordered if not a["hard"]), key=_rank)
    prev = assessed.get(previous_mode)

    reasons: list[str] = []
    codes: list[str] = []
    if not viable:
        action, chosen = "no_option", prev
        for a in ordered:
            for code, text in a["hard"]:
                reasons.append(f"{a['label']}：{text}")
                codes.append(code)
    else:
        best = viable[0]
        if prev is None:
            action, chosen = "init", best
        elif prev["hard"]:
            action, chosen = "switch", best
            reasons = [text for _, text in prev["hard"]]
            codes = [code for code, _ in prev["hard"]]
        elif (best["mode"] != prev["mode"]
              and len(best["soft"]) < len(prev["soft"])
              and best["minutes"] <= prev["minutes"] + SWITCH_TOLERANCE_MINUTES):
            action, chosen = "switch", best
            reasons = [text for _, text in prev["soft"]]
            codes = [code for code, _ in prev["soft"]]
        else:
            action, chosen = "keep", prev

    return {
        "status": "ok",
        "action": action,
        "checked": checked,
        "mode": chosen["mode"] if chosen else previous_mode,
        "mode_label": _label(chosen["mode"] if chosen else previous_mode),
        "previous_mode": previous_mode,
        "summary": _summary(action, prev, chosen, reasons),
        "reasons": reasons,
        "reason_codes": codes,
        # 前端存起來，下一輪帶回來：已經接受的風險就不必為它重新比較四種方式
        "soft_codes": [code for code, _ in chosen["soft"]] if chosen else [],
        "facts": ({"minutes": chosen["minutes"], "leave_by": chosen["leave_by"],
                   "risks": [text for _, text in chosen["soft"]]} if chosen else None),
        "options": [_compact(a) for a in ordered],
        "simulated_scenarios": extras.get("scenarios", []),
        "at": now.isoformat(timespec="seconds"),
    }


def replan(origin: str, vehicle_type: str = "機車", schedule_path: str = "",
           previous_mode: str | None = None, now: datetime | None = None,
           simulated: bool = False, known_soft=(),
           plan_fn=plan_departure, compare_fn=compare_plans,
           bus_fn=get_bus_eta, rain_fn=get_rain_now) -> dict:
    """檢查目前的交通方式還行不行；不行就重新比較並改換，回傳決定與原因。

    Args:
        origin: 出發地。
        vehicle_type: 開車模式要停的車種。
        schedule_path: 課表路徑，留空用預設。
        previous_mode: 上一輪的交通方式；None 代表第一次，直接給建議。
        now: 用哪個時間當「現在」；留空是真實時間。
        simulated: 這個 now 是不是模擬的（決定要不要採用即時觀測）。
        known_soft: 上一輪已接受的軟風險代碼；只有同樣的風險時不重新比較。

    Returns:
        dict，含 status、action（keep／switch／init／no_option）、mode、summary、
        reasons、soft_codes、options（各方式的簡要結果）、checked（quick 表示只檢查
        了目前這一種，full 表示比較了全部）、at。
    """
    if now is None:
        now = datetime.now(ZoneInfo(load_settings().timezone))
    known = set(known_soft)
    extras = None      # 快速檢查查到的觀測，升級成完整比較時直接沿用

    if previous_mode in MODES:
        plan = plan_fn(origin, previous_mode, vehicle_type, schedule_path, now=now)
        if plan.get("status") != "ok":
            return {"status": plan.get("status", "error"),
                    "error_message": plan.get("error_message"), "note": plan.get("note")}
        option = build_option(previous_mode, plan, now,
                              datetime.fromisoformat(plan["class_starts_at"]))
        extras = observe(origin, simulated, previous_mode == "transit", bus_fn, rain_fn)
        hard, soft = assess(option, extras, now)
        if not hard and {code for code, _ in soft} <= known:
            return decide(previous_mode, [option], extras, now, checked="quick")

    comparison = compare_fn(origin, vehicle_type, schedule_path, now=now)
    if comparison["status"] != "ok":
        return {"status": comparison["status"],
                "error_message": comparison.get("error_message"),
                "note": comparison.get("note")}
    extras = observe(origin, simulated, True, bus_fn, rain_fn, extras)
    return decide(previous_mode if previous_mode in MODES else None,
                  comparison["options"], extras, now, checked="full")


def replan_commute(previous_mode: str = "", origin: str = "", vehicle_type: str = "機車") -> dict:
    """給 Agent 用：檢查目前的交通方式還行不行，不行就建議改換。

    適用時機：使用者已經選了交通方式，問「還是這樣去嗎」、「下雨了要不要改」、
    「YouBike 還有車嗎，要不要換」時使用。會用真實時間與即時觀測（雨量站、公車班次）。

    Args:
        previous_mode: 目前的交通方式 walking／bicycling／transit／driving；
            留空代表還沒選，直接給建議。
        origin: 出發地；留空用預設地址。
        vehicle_type: 開車模式要停的車種，"機車" 或 "汽車"。

    Returns:
        dict，action 為 keep（維持）、switch（改換）、init（初次建議）或
        no_option（都不可行）；summary 是可直接轉述的一句話，reasons 是原因。
        時間為估算或實際路線，依各方案的 is_estimate 而定。
    """
    settings = load_settings()
    start = (origin or "").strip() or settings.default_origin
    if not start:
        return {"status": "error", "error_message": "沒有出發地，也沒有設定 DEFAULT_ORIGIN"}
    return replan(start, vehicle_type, "", previous_mode or None)
