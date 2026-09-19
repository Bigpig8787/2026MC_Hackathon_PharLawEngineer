"""Skill 層：回答「我現在該出發了嗎」。

這是 CampusPulse Agent Loop 裡 Planning 的核心：把下一堂課的時間、路程時間
與到教室後的緩衝時間加總，倒推出發時刻，再跟現在比較。

緩衝時間不是隨便抓的：導航算到的是大樓門口，但實際上還要找教室、爬樓梯、
進門坐定。重要的課（考試、報告）緩衝更多，因為遲到的代價不一樣。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from api import load_settings
from commute_agent.skills.bike_plan import plan_bike_journey_auto
from commute_agent.skills.locate_place import locate_course_place
from commute_agent.skills.trip_plan import estimate_trip, plan_ride_and_walk
from commute_agent.tools.class_schedule import get_next_class
from commute_agent.tools.ncku_room import lookup_room
from commute_agent.tools.weather import get_weather

# 這些交通方式會淋到雨，下雨時值得建議改搭有遮蔽的公車
EXPOSED_MODES = ("walking", "bicycling", "driving")

# 導航只算到大樓門口，進到教室坐定還要時間
ARRIVAL_BUFFER_MINUTES = 8

# 課名含這些字代表遲到代價高，緩衝加倍
HIGH_STAKES_KEYWORDS = ("考", "報告", "發表", "實驗", "面試", "口試")
HIGH_STAKES_EXTRA_MINUTES = 10


def buffer_minutes_for(course_name: str) -> int:
    """依課程性質決定緩衝時間。考試與報告遲到的代價高，多留一點。"""
    name = course_name or ""
    extra = HIGH_STAKES_EXTRA_MINUTES if any(k in name for k in HIGH_STAKES_KEYWORDS) else 0
    return ARRIVAL_BUFFER_MINUTES + extra


def travel_for_mode(origin: str, building: str, travel_mode: str,
                    vehicle_type: str = "機車") -> dict:
    """算某一種交通方式從起點到大樓要多久。

    每種方式的「一趟路」定義不同，不能都當成單純的兩點移動：
    - 騎車開車要先停車再走過去，所以是騎乘＋步行兩段。
    - 騎 YouBike 要先走到借車站、最後從還車站走到教室，是三段；
      只算騎乘時間會嚴重低估（實測 5 分 vs 實際 14 分）。
    - 步行與大眾運輸才是單純的一段。

    回傳 minutes（算不出來時為 None）、is_estimate、note、
    parking（只有停車情境才有）與 bike（只有 YouBike 情境才有）。
    """
    if travel_mode == "driving":
        journey = plan_ride_and_walk(origin, building, vehicle_type)
        if journey["status"] != "ok":
            # 找不到停車場或算不出騎車路線時 ride／walk 是 None，不是空 dict；
            # journey.get("ride", {}) 的預設值只在鍵不存在時生效，鍵存在但值是
            # None 照樣會回 None，接著 .get(...) 就丟 AttributeError 把整支炸掉。
            # 跟 bicycling 分支一樣，查不到就老實說算不出來，不要讓整個比較掛掉。
            return {"minutes": None, "is_estimate": True,
                    "note": journey.get("error_message", ""),
                    "parking": None, "bike": None}
        ride = journey.get("ride") or {}
        return {"minutes": journey.get("total_minutes"),
                "is_estimate": bool(ride.get("is_estimate", True)),
                "note": journey.get("note", ""),
                "parking": journey.get("lot"), "bike": None}

    if travel_mode == "bicycling":
        journey = plan_bike_journey_auto(origin, building)
        if journey["status"] != "ok":
            # 附近沒有可借的車就不該假裝騎得成，但也不必讓整個比較掛掉
            return {"minutes": None, "is_estimate": True,
                    "note": journey.get("error_message", ""),
                    "parking": None, "bike": None}
        return {"minutes": journey["total_minutes"],
                "is_estimate": bool(journey["ride"].get("is_estimate", True)),
                "note": journey.get("note", ""), "parking": None,
                "bike": {"from_station": journey["from_station"],
                         "to_station": journey["to_station"],
                         "walk_to_station": journey["walk_to_station"],
                         "ride": journey["ride"],
                         "walk_to_destination": journey["walk_to_destination"],
                         "map_link": journey["map_link"]}}

    trip = estimate_trip(origin, building, travel_mode)
    return {"minutes": trip.get("minutes"), "is_estimate": trip.get("is_estimate", True),
            "note": trip.get("note", ""), "parking": None, "bike": None}


def _resolve_building(entry: dict) -> str:
    """把課表寫的地點換成 GIS 的正式大樓名稱，查不到就用原文。

    先試教室代碼（最準），查不到再交給 locate_course_place 用原文去換
    ——它會依序試 GIS 原文、剪短前綴、Gemini 讀關鍵字。這一步很重要：
    像「成大綜合體育館-體育館羽球場」這種沒有教室代碼的課，以前會整串
    原文往下傳，plan_parking／geocode_place 都認不得這種寫法，
    整堂課的騎車、單車路線就會算不出來（甚至讓 travel_for_mode 崩潰，
    見下方的 status 防呆）。改用 locate_course_place 後這裡也一併吃到
    Gemini 讀懂的大樓名，跟教室位置卡、導航連結用的是同一套解析。
    """
    query = entry.get("room_query")
    if query:
        found = lookup_room(query)
        exact = [c for c in found.get("candidates", []) if c["exact_match"]]
        chosen = exact[0] if exact else (found.get("candidates") or [None])[0]
        if chosen:
            return chosen["building_name"]

    place = locate_course_place(entry["location"], query or "")
    return place["name"] if place["status"] == "ok" else entry["location"]


def plan_departure(origin: str = "", travel_mode: str = "walking",
                   vehicle_type: str = "機車", schedule_path: str = "") -> dict:
    """算出使用者該幾點出發才趕得上下一堂課。

    適用時機：使用者問「我該出發了嗎」、「來得及嗎」、「幾點要走」時使用。
    會自己查課表與現在時間，不必先問使用者今天星期幾或下一堂是什麼。

    Args:
        origin: 出發地。留空則用 .env 的 DEFAULT_ORIGIN。
        travel_mode: "walking"、"bicycling"、"driving" 或 "transit"。
            選 driving 時會自動把停車時間算進去。
        vehicle_type: driving 時要停的車種，"機車" 或 "汽車"。
        schedule_path: 要依哪一份課表規劃。留空表示用設定裡的預設課表；
            網頁會傳入使用者上傳的那一份。

    Returns:
        dict，包含：
        - status: "ok"、"no_class"（課表裡沒有接下來的課）或 "error"
        - verdict: "plenty"（時間充裕）、"leave_now"（該出發了）或
          "too_late"（已經來不及準時抵達）
        - leave_at: 建議出發時刻
        - minutes_until_departure: 距離該出發還有幾分鐘；負數代表已經超過
        - travel_minutes、buffer_minutes: 路程時間與進教室緩衝
        - course: 下一堂課的名稱、時間與地點
        - is_estimate: 路程時間是否為估算值
        - note: 時間來源與限制說明
    """
    settings = load_settings()
    origin = (origin or "").strip() or settings.default_origin
    if not origin:
        return {"status": "error", "verdict": None,
                "error_message": "沒有出發地，也沒有設定 DEFAULT_ORIGIN"}

    schedule = get_next_class(schedule_path)
    if schedule["status"] == "error":
        return {"status": "error", "verdict": None,
                "error_message": schedule.get("error_message", "課表讀取失敗")}
    upcoming = schedule.get("next_class")
    if not upcoming:
        return {"status": "no_class", "verdict": None,
                "note": "課表裡找不到接下來的課。"}

    building = _resolve_building(upcoming)

    leg = travel_for_mode(origin, building, travel_mode, vehicle_type)
    travel, is_estimate = leg["minutes"], leg["is_estimate"]
    source_note, parking = leg["note"], leg["parking"]

    buffer = buffer_minutes_for(upcoming["name"])
    starts_at = datetime.fromisoformat(upcoming["starts_at"])
    now = datetime.now(ZoneInfo(settings.timezone))

    result = {
        "status": "ok",
        "course": {"name": upcoming["name"], "day_zh": upcoming["day_zh"],
                   "start_time": upcoming["start_time"], "location": upcoming["location"],
                   "building": building},
        "origin": origin,
        "travel_mode": travel_mode,
        "travel_minutes": travel,
        "buffer_minutes": buffer,
        "parking": parking,
        "bike": leg["bike"],
        "is_estimate": is_estimate,
        "now": now.isoformat(timespec="seconds"),
        "class_starts_at": upcoming["starts_at"],
    }

    if travel is None:
        return {**result, "verdict": None, "leave_at": None,
                "minutes_until_departure": None,
                "note": f"算不出路程時間，因此無法推算出發時刻。{source_note}"}

    leave_at = starts_at - timedelta(minutes=travel + buffer)
    remaining = round((leave_at - now).total_seconds() / 60)

    if remaining < 0:
        verdict = "too_late"
    elif remaining <= 5:
        verdict = "leave_now"
    else:
        verdict = "plenty"

    # 出發當下的天氣才有意義，不是現在的天氣
    weather = get_weather(when_iso=leave_at.isoformat())
    advice = None
    if weather["status"] == "ok" and weather.get("will_rain") and travel_mode in EXPOSED_MODES:
        advice = (f"出發時降雨機率 {weather['rain_probability']}%，"
                  "這個交通方式會淋到雨，可考慮改搭公車或提早出門。")

    return {**result, "verdict": verdict,
            "leave_at": leave_at.isoformat(timespec="seconds"),
            "minutes_until_departure": remaining,
            "weather": {k: weather.get(k) for k in
                        ("weather", "rain_probability", "will_rain",
                         "temperature", "apparent_temperature")}
                       if weather["status"] == "ok" else None,
            "weather_advice": advice,
            "note": f"路程 {travel} 分＋進教室緩衝 {buffer} 分。{source_note}"}
