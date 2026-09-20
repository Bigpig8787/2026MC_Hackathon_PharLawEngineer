"""Skill 層：課堂進行中，判斷你在不在上課的教室；不在就算遲到或缺席。

情境：現在是 5、6 節的時間，課表寫資訊系館有課，但你輸入的所在地（或瀏覽器給的
即時位置）不在那棟大樓——這代表你沒在教室。這支算出你離教室多遠、課已經開始多久、
走過去要多久，並建議該寫「遲到信」還是「請假信」。

判斷的是「在上課的大樓附近」，不是「在教室裡」：座標只到大樓中心點，分不出樓層或
哪一間，所以用半徑判斷。GPS 本身有誤差（室內常差幾十公尺），半徑會依定位精度放寬，
但有上限，免得精度很差時連隔壁棟都算在教室。

不用預設地址（住家）當你的位置：那只是「出發地」的預設值，不是你現在在哪。
沒有位置就明說沒有，不猜、也不因此判你缺席。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from api import load_settings
from commute_agent.skills.locate_place import locate_course_place
from commute_agent.tools.class_schedule import (
    PROJECT_ROOT,
    SchemaError,
    find_classes,
    load_courses,
)
from commute_agent.tools.geocode import geocode_place
from commute_agent.tools.ncku_geo import estimate_minutes, haversine_meters

# 距教室中心點這麼近就算在教室所在的大樓。校內大樓的中心點到最遠的角落
# 可以有近百公尺，所以不能抓太小
AT_CLASS_RADIUS_METERS = 120

# GPS 精度很差時（例如 800 公尺）半徑不能跟著無限放大，否則隔壁棟也算在教室
MAX_RADIUS_METERS = 300

# 走過去之後，課還剩這麼久以上才值得進教室；不到就建議直接請假或事後說明
WORTH_ATTENDING_MINUTES = 15

NOTE = ("判斷的是「在上課的大樓附近」（半徑 {radius} 公尺），"
        "座標只到大樓中心點，分不出樓層或哪一間教室。")


def _class_info(current: dict, place: dict | None) -> dict:
    return {"name": current["name"], "location": current["location"],
            "building": (place or {}).get("name") or "",
            "starts_at": current["starts_at"], "ends_at": current["ends_at"]}


def _advice(at_class: bool, cls: dict, distance: int, elapsed: int, remaining: int,
            walk: int, late_by: int, suggestion: str | None) -> str:
    """一句話說明，全部由數字決定，沒有模型參與。"""
    where = cls["building"] or cls["location"]
    if at_class:
        return f"你在{where}附近（距教室約 {distance} 公尺）；課已開始 {elapsed} 分鐘，還剩 {remaining} 分鐘。"
    base = (f"你不在上課的{where}（距離約 {distance} 公尺）；"
            f"課已開始 {elapsed} 分鐘、還剩 {remaining} 分鐘，走過去約 {walk} 分。")
    if suggestion == "late":
        return base + f"預計晚到約 {late_by} 分鐘，建議先通知老師會遲到。"
    return (base + f"到的時候只剩約 {max(0, remaining - walk)} 分鐘，不太值得進教室，"
            "建議直接請假，或事後向老師說明。")


def check_attendance(current: dict | None, now: datetime, place_text: str = "",
                     lat: float | None = None, lon: float | None = None,
                     accuracy_m: float | None = None,
                     locate=locate_course_place, geocode=geocode_place) -> dict:
    """判斷正在上的這堂課，你人在不在教室；不在的話算遲到還是缺席，並給建議。

    Args:
        current: 正在上的課（class_schedule 的 entry，要有 name、location、
            room_query、starts_at、ends_at）；沒有課就傳 None。
        now: 現在時間（含時區）。
        place_text: 使用者輸入的所在地，例如「成大圖書館」。
        lat、lon: 即時位置（瀏覽器定位）。兩者都給時優先於 place_text。
        accuracy_m: 定位精度（公尺），用來放寬「在教室」的半徑。
        locate、geocode: 把地點換成座標的函式，測試時換成假的。

    Returns:
        dict，包含：
        - status: "ok"、"no_class"（現在沒在上課）、"no_location"（沒給位置）、
          "unknown_location"（查不到使用者輸入的地點）、"unavailable"
          （查不到上課教室的位置）
        - at_class: 是否在教室所在的大樓附近（status 為 ok 時才有）
        - distance_m、radius_m: 距教室多遠，以及判斷「在教室」用的半徑
        - elapsed_minutes、remaining_minutes: 課已開始多久、還剩多久
        - walk_minutes、late_by: 不在教室時，走過去要多久、預計晚到幾分鐘
        - suggestion: 不在教室時建議 "late"（寫遲到信）或 "leave"（寫請假信）
        - advice: 一句話說明；here: 使用者位置與來源（typed／gps）
    """
    if not current:
        return {"status": "no_class", "note": "現在沒有在上課。"}

    class_place = locate(current["location"], current.get("room_query", ""))
    cls = _class_info(current, class_place if class_place.get("status") == "ok" else None)

    if class_place.get("status") != "ok":
        return {"status": "unavailable", "class": cls,
                "note": f"查不到「{current['location']}」的位置，無法判斷你在不在教室。"}

    starts_at = datetime.fromisoformat(current["starts_at"])
    ends_at = datetime.fromisoformat(current["ends_at"])
    elapsed = round((now - starts_at).total_seconds() / 60)
    remaining = round((ends_at - now).total_seconds() / 60)

    if lat is not None and lon is not None:
        here = {"name": "目前位置", "lat": float(lat), "lon": float(lon), "source": "gps"}
    elif (place_text or "").strip():
        found = geocode(place_text.strip())
        if found.get("status") != "ok":
            return {"status": "unknown_location", "class": cls,
                    "note": f"查不到「{place_text.strip()}」的位置，無法判斷你在不在教室。"}
        here = {"name": found.get("name") or place_text.strip(), "lat": found["lat"],
                "lon": found["lon"], "source": "typed"}
    else:
        return {"status": "no_location", "class": cls,
                "elapsed_minutes": elapsed, "remaining_minutes": remaining,
                "note": "沒有你的位置：請輸入所在地，或使用即時位置。"}

    distance = haversine_meters(here["lat"], here["lon"], class_place["lat"], class_place["lon"])
    radius = AT_CLASS_RADIUS_METERS
    if here["source"] == "gps":
        radius = min(MAX_RADIUS_METERS, max(AT_CLASS_RADIUS_METERS, accuracy_m or 0))
    at_class = distance <= radius

    walk = 0 if at_class else estimate_minutes(distance, "walking")
    late_by = 0 if at_class else max(1, elapsed + walk)
    suggestion = None
    if not at_class:
        suggestion = "late" if remaining - walk >= WORTH_ATTENDING_MINUTES else "leave"

    notes = [NOTE.format(radius=round(radius))]
    if not class_place.get("is_verified"):
        notes.append("上課地點的座標只來自 Google、未經成大 GIS 驗證，可能不準。")

    return {
        "status": "ok",
        "class": cls,
        "here": here,
        "at_class": at_class,
        "distance_m": round(distance),
        "radius_m": round(radius),
        "elapsed_minutes": elapsed,
        "remaining_minutes": remaining,
        "walk_minutes": walk,
        "late_by": late_by,
        "suggestion": suggestion,
        "advice": _advice(at_class, cls, round(distance), elapsed, remaining, walk, late_by,
                          suggestion),
        "note": "".join(notes),
    }


def check_attendance_now(place: str = "") -> dict:
    """給 Agent 用：現在正在上課的話，判斷使用者輸入的所在地在不在上課的教室。

    適用時機：使用者說「我現在在圖書館」，而現在剛好是上課時間，想知道自己是不是
    遲到了、該寫遲到信還是請假信時使用。用真實時間與預設課表。

    Args:
        place: 使用者現在所在的地點，例如「成大圖書館」。不要拿預設地址（住家）充數。

    Returns:
        dict，status 為 "ok"、"no_class"、"no_location"、"unknown_location" 或
        "unavailable"。ok 時 at_class 表示是否在教室附近；不在時 suggestion 為
        "late"（建議寫遲到信）或 "leave"（建議請假），advice 是可直接轉述的一句話。
        判斷只到「大樓附近」，轉述時要講明分不出樓層或哪一間教室。
    """
    settings = load_settings()
    now = datetime.now(ZoneInfo(settings.timezone))
    path = Path(settings.class_schedule_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        return {"status": "error", "error_message": f"找不到課表檔案：{path}"}

    try:
        current, _ = find_classes(load_courses(path), now)
    except (SchemaError, ValueError) as exc:
        return {"status": "error", "error_message": f"課表格式異常：{exc}"}
    return check_attendance(current, now, place_text=place)
