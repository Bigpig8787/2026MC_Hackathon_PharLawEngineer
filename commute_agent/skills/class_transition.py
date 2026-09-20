"""Skill 層：連著上課時，從上一堂的教室走到下一堂來不來得及。

plan_departure 回答的是「從出發地到下一堂課要幾點走」，出發地由使用者自己填。
但學生一天裡最常遇到的其實是課間：上一堂下課，十分鐘後下一堂在別棟大樓開始。
這時出發地根本不必問——就是上一堂的教室，出發時刻是下課那一刻
（已經下課的話就是現在）。

距離與時間全用成大 GIS 的大樓座標估算，不呼叫任何計費 API：課間的距離通常
只有幾百公尺，不值得為它花 Google 額度，而且結果會明確標示是估算值。
兩間教室查不到位置時就直說算不出來，不拿別棟的座標充數。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from api import load_settings
from commute_agent.skills.departure_plan import ARRIVAL_BUFFER_MINUTES, buffer_minutes_for
from commute_agent.skills.locate_place import locate_course_place
from commute_agent.tools.class_schedule import (
    PROJECT_ROOT,
    SchemaError,
    find_classes,
    find_recent_class,
    load_courses,
)
from commute_agent.tools.ncku_geo import estimate_minutes, haversine_meters

# 下課後多久內，還當作人在上一堂教室附近
RECENT_END_MINUTES = 20

# 上一堂下課到下一堂開始超過這麼久，就不算課間轉場（例如中午的長空堂）
MAX_GAP_MINUTES = 180

# 課間的進教室緩衝比出門通勤少：人已經在校園裡，只需要收拾東西與找位子。
# 考試、報告這類課仍會沿用 departure_plan 的規則加長。
TRANSITION_BUFFER_MINUTES = 3

# 扣掉路程與緩衝後還剩這麼多分鐘以上，才算時間充裕
COMFORTABLE_MARGIN_MINUTES = 5

# 兩間教室的座標距離小於這個值，視為同一棟
SAME_BUILDING_METERS = 40

VERDICT_LABELS = {"comfortable": "時間充裕", "tight": "很趕", "late": "會遲到"}


def assess_transition(gap_minutes: float, travel_minutes: int, buffer_minutes: int) -> dict:
    """依「下課到上課的空檔」扣掉路程與緩衝後剩多少，判斷來不來得及。純函式。"""
    margin = round(gap_minutes - travel_minutes - buffer_minutes)
    if margin >= COMFORTABLE_MARGIN_MINUTES:
        verdict = "comfortable"
    elif margin >= 0:
        verdict = "tight"
    else:
        verdict = "late"
    return {"verdict": verdict, "margin_minutes": margin, "late_by": max(0, -margin)}


def _distance_m(src: dict, dst: dict) -> float:
    """兩處教室的直線距離。同一棟（代碼相同或幾乎重疊）回 0。"""
    if src.get("build_id") and src.get("build_id") == dst.get("build_id"):
        return 0.0
    distance = haversine_meters(src["lat"], src["lon"], dst["lat"], dst["lon"])
    return 0.0 if distance < SAME_BUILDING_METERS else distance


def _minutes(distance: float, mode: str) -> int:
    # estimate_minutes 最少回 1 分，但同一棟大樓真的不必移動
    return 0 if distance == 0 else estimate_minutes(distance, mode)


def _advice(verdict: str, to_place: str, gap: int, walk: int, bike: int,
            late_by: int, bike_makes_it: bool, same_building: bool) -> str:
    """一句話的建議，全部由數字決定，沒有任何模型參與。"""
    if same_building:
        return f"下一堂同在{to_place}，不必換棟；下課後有 {gap} 分鐘。"
    if verdict == "comfortable":
        return f"下課後有 {gap} 分鐘，走路約 {walk} 分，時間充裕。"
    if verdict == "tight":
        return f"下課後只有 {gap} 分鐘，走路約 {walk} 分，一下課就要馬上出發。"
    base = f"下課後只有 {gap} 分鐘，走路約 {walk} 分，預估會遲到約 {late_by} 分。"
    if bike_makes_it:
        return base + f"改騎自行車約 {bike} 分可以趕上。"
    return base + "即使騎車也趕不上，建議提早離開上一堂，或事先告知老師。"


def plan_class_transition(previous: dict, upcoming: dict, now: datetime,
                          locate=locate_course_place) -> dict:
    """算從上一堂的教室走到下一堂的教室，來不來得及。

    Args:
        previous: 上一堂課（class_schedule 的課程 entry，要有 name、location、
            room_query、ends_at）。
        upcoming: 下一堂課（要有 name、location、room_query、starts_at）。
        now: 現在時間（含時區）。已經下課時，出發時刻就是現在，不是下課時刻。
        locate: 把課表地點換成座標的函式，測試時換成假的。

    Returns:
        dict，包含：
        - status: "ok"，或 "unavailable"（查不到其中一間教室的位置）
        - verdict: "comfortable"（時間充裕）、"tight"（很趕）或 "late"（會遲到）；
          算不出來時為 None
        - gap_minutes: 從出發時刻到下一堂開始的空檔
        - walk_minutes、bike_minutes、distance_m、buffer_minutes: 路程與緩衝
        - margin_minutes、late_by: 扣掉路程與緩衝後剩多少；遲到時 late_by 為遲到分鐘數
        - advice: 一句話建議
        - is_estimate: 恆為 True，時間是座標直線距離估算，不含樓層內移動
    """
    src = locate(previous["location"], previous.get("room_query", ""))
    dst = locate(upcoming["location"], upcoming.get("room_query", ""))

    ends_at = datetime.fromisoformat(previous["ends_at"])
    starts_at = datetime.fromisoformat(upcoming["starts_at"])
    leaves_after = max(now, ends_at)
    gap = round((starts_at - leaves_after).total_seconds() / 60)

    result = {
        "status": "ok",
        "from": {"course": previous["name"],
                 "place": src.get("name") or previous["location"],
                 "ends_at": previous["ends_at"]},
        "to": {"course": upcoming["name"],
               "place": dst.get("name") or upcoming["location"],
               "starts_at": upcoming["starts_at"]},
        "leaves_after": leaves_after.isoformat(timespec="seconds"),
        "gap_minutes": gap,
        "is_estimate": True,
    }

    unresolved = [entry["location"] for entry, place in ((previous, src), (upcoming, dst))
                  if place.get("status") != "ok"]
    if unresolved:
        return {**result, "status": "unavailable", "verdict": None,
                "note": f"查不到「{'」、「'.join(unresolved)}」的位置，算不出課間轉場時間。"}

    distance = _distance_m(src, dst)
    walk, bike = _minutes(distance, "walking"), _minutes(distance, "bicycling")
    # 緩衝沿用 departure_plan 的規則：基本值另訂，考試與報告加長的部分照舊
    buffer = TRANSITION_BUFFER_MINUTES + (
        buffer_minutes_for(upcoming["name"]) - ARRIVAL_BUFFER_MINUTES)

    walking = assess_transition(gap, walk, buffer)
    bike_makes_it = assess_transition(gap, bike, buffer)["margin_minutes"] >= 0

    notes = ["時間為座標直線距離估算（已乘繞路係數），不含樓層內移動與等電梯。"]
    if not (src.get("is_verified") and dst.get("is_verified")):
        notes.append("其中一處位置只來自 Google、未經成大 GIS 驗證，可能不準。")

    return {
        **result,
        **walking,
        "distance_m": round(distance),
        "walk_minutes": walk,
        "bike_minutes": bike,
        "buffer_minutes": buffer,
        "same_building": distance == 0,
        "advice": _advice(walking["verdict"], result["to"]["place"], gap, walk, bike,
                          walking["late_by"], bike_makes_it, distance == 0),
        "note": "".join(notes),
    }


def find_transition(courses: list[dict], now: datetime, current: dict | None = None,
                    upcoming: dict | None = None, locate=locate_course_place) -> dict | None:
    """在課表裡找出「上一堂→下一堂」的課間轉場並算出來，不適用時回 None。

    上一堂是正在上的課，或 RECENT_END_MINUTES 內剛下課的那一堂。下一堂必須
    跟上一堂同一天、間隔不超過 MAX_GAP_MINUTES；排課重疊的也不算。

    current、upcoming 呼叫端已經用 find_classes 算過就傳進來，省得重算一次。
    """
    if current is None and upcoming is None:
        current, upcoming = find_classes(courses, now)

    previous = current or find_recent_class(courses, now, RECENT_END_MINUTES)
    if not previous or not upcoming:
        return None

    ends_at = datetime.fromisoformat(previous["ends_at"])
    starts_at = datetime.fromisoformat(upcoming["starts_at"])
    if starts_at < ends_at or starts_at.date() != ends_at.date():
        return None
    if (starts_at - max(now, ends_at)).total_seconds() / 60 > MAX_GAP_MINUTES:
        return None

    return plan_class_transition(previous, upcoming, now, locate)


def plan_next_transition(schedule_path: str = "") -> dict:
    """查現在有沒有課間轉場，並算出從上一堂教室走到下一堂來不來得及。

    適用時機：使用者正在上課或剛下課，問「下一堂來得及嗎」、「要換教室了，
    走過去要多久」時使用。出發地就是上一堂的教室，不必再問使用者在哪。

    Args:
        schedule_path: 要讀哪一份課表。留空表示用設定裡的預設課表。

    Returns:
        dict，status 為 "ok"、"unavailable"（查不到教室位置）、
        "not_applicable"（現在沒有前後兩堂連著的課）或 "error"。
        "ok" 時包含 verdict（comfortable／tight／late）、gap_minutes、
        walk_minutes、bike_minutes、late_by、advice；is_estimate 恆為 True，
        轉述時要說「大約」。
    """
    settings = load_settings()
    now = datetime.now(ZoneInfo(settings.timezone))
    path = Path(schedule_path or settings.class_schedule_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        return {"status": "error", "error_message": f"找不到課表檔案：{path}"}

    try:
        courses = load_courses(path)
        found = find_transition(courses, now)
    except (SchemaError, ValueError) as exc:
        return {"status": "error", "error_message": f"課表格式異常：{exc}"}

    if found is None:
        return {"status": "not_applicable",
                "note": "現在不是課間：沒有正在上或剛下課的課，或下一堂不在同一天、"
                        "隔得太久。要問從家裡出發，請改用 plan_departure。"}
    return found
