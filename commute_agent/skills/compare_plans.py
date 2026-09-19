"""Skill 層：把各種交通方式並排比較，回答「我該怎麼去」。

departure_plan 一次只看一種交通方式，這支把四種都跑過再排出建議。

主要比較軸是「最晚幾點得出發」：不論課在兩小時後還是兩天後，這個數字都成立，
而且直接反映各方案的快慢差距。超過這個時刻就會標示來不及——路程長到跨縣市時
這件事可能在課前一天就成立，所以不以「離上課還有多久」去限制警告時機。

刻意不輸出「準時機率」這種百分比：我們沒有歷史變異數，算出來的數字是
憑空捏造的。改成列出具體風險（會遲到幾分鐘、車位剩多少、出發時會不會下雨），
使用者自己看得懂，也禁得起追問。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from api import load_settings
from commute_agent.skills.departure_plan import plan_departure
from commute_agent.tools.route_link import TRAVEL_MODE_LABELS

MODES = ("walking", "bicycling", "transit", "driving")

# 停車場剩餘車位低於這個數，就算它現在還有位，到的時候也可能沒了
PARKING_RISK_THRESHOLD = 60


def _risks(option: dict, late_by: int, plan: dict) -> list[str]:
    """把這個方案的具體風險列出來，不做成分數或機率。"""
    found = []
    # 還沒到出發時刻時 late_by 自然是 0，不需要額外用「課還很久」去壓抑警告——
    # 那樣反而會在人還在外縣市、路程長到已經來不及時把警告吃掉
    if late_by > 0:
        found.append(f"已經超過最晚出發時間 {late_by} 分鐘")
    if plan.get("weather_advice"):
        found.append(plan["weather_advice"])
    lot = plan.get("parking")
    if lot and lot.get("available") is not None:
        if lot["available"] < PARKING_RISK_THRESHOLD:
            found.append(f"{lot['name']}目前只剩 {lot['available']} 位，抵達時可能已滿")
    if option["minutes"] is None:
        found.append("算不出路程時間")
    return found


def compare_plans(origin: str = "", vehicle_type: str = "機車",
                  schedule_path: str = "") -> dict:
    """比較各種交通方式，算出現在出發各自會幾點抵達、會不會遲到。

    適用時機：使用者問「我該怎麼去」、「騎車還是搭公車比較好」、
    「來得及嗎」時使用，一次看完所有選項再決定。

    Args:
        origin: 出發地。留空則用 .env 的 DEFAULT_ORIGIN。
        vehicle_type: 開車模式要停的車種，"機車" 或 "汽車"。
        schedule_path: 要依哪一份課表比較。留空表示用設定裡的預設課表；
            網頁會傳入使用者上傳的那一份，否則比的會是別堂課。

    Returns:
        dict，包含：
        - status: "ok"、"no_class" 或 "error"
        - options: 每種交通方式一筆，含 mode、label、minutes、
          leave_by（最晚出發時刻）、arrive_if_leave_now、
          late_by（已超過最晚出發時刻幾分鐘）、risks（具體風險文字清單）、
          weather（該方案出發時刻的天氣與氣溫，查不到時為 None）
        - best: 建議的方案。快上課時先排除已來不及的，其餘情況比風險數量與路程
        - course: 下一堂課的資訊
    """
    settings = load_settings()
    now = datetime.now(ZoneInfo(settings.timezone))

    options, course, class_starts = [], None, None
    for mode in MODES:
        plan = plan_departure(origin, mode, vehicle_type, schedule_path)
        if plan["status"] != "ok":
            return {"status": plan["status"], "options": [], "best": None,
                    "error_message": plan.get("error_message"),
                    "note": plan.get("note")}

        course = course or plan["course"]
        class_starts = class_starts or datetime.fromisoformat(plan["class_starts_at"])

        minutes = plan["travel_minutes"]
        option = {
            "mode": mode,
            "label": TRAVEL_MODE_LABELS[mode],
            "minutes": minutes,
            "buffer_minutes": plan["buffer_minutes"],
            "is_estimate": plan["is_estimate"],
            "parking": plan.get("parking"),
            "bike": plan.get("bike"),
            # 每個方案的出發時刻不同，天氣是各自出發當下那一筆，不能共用一份
            "weather": plan.get("weather"),
            "leave_by": None,
            "arrive_if_leave_now": None,
            "late_by": None,
        }

        if minutes is not None:
            total = minutes + plan["buffer_minutes"]
            # 最晚出發時刻：不論課在幾天後都成立，是方案之間最穩定的比較軸
            leave_by = class_starts - timedelta(minutes=total)
            option["leave_by"] = leave_by.isoformat(timespec="seconds")
            # 現在出發會幾點到：只有快上課時才有參考價值，課在兩天後時
            # 「現在出發 20:56 到」對星期一早上的課毫無意義
            arrive = now + timedelta(minutes=total)
            option["arrive_if_leave_now"] = arrive.isoformat(timespec="seconds")
            option["late_by"] = max(0, round((now - leave_by).total_seconds() / 60))

        option["risks"] = _risks(option, option["late_by"] or 0, plan)
        options.append(option)

    if course is None:
        return {"status": "no_class", "options": [], "best": None}

    def rank(option: dict) -> tuple:
        # 算不出時間的排最後：不知道會不會遲到，就不該拿來推薦
        unknown = option["minutes"] is None
        return (unknown, option["late_by"] or 0, len(option["risks"]),
                option["minutes"] or 0)

    ranked = sorted(options, key=rank)
    best = ranked[0] if ranked and ranked[0]["minutes"] is not None else None

    return {
        "status": "ok",
        "now": now.isoformat(timespec="seconds"),
        "course": course,
        "class_starts_at": class_starts.isoformat(timespec="seconds"),
        "options": options,
        "best": best,
        "note": "最晚出發時刻＝上課時間−路程−進教室緩衝；標示為估算的時間並非 Google 實際路線。",
    }
