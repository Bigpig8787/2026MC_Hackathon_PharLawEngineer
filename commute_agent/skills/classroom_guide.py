"""Skill 層：回答「這間教室在哪、在幾樓、長什麼樣子」。

把三件事串成一張教室導覽卡：
- 位置：成大 GIS 的大樓名稱與中心點座標，加上一條導航連結。
- 平面圖：picture/ 裡那一層的截圖，讓使用者到了大樓還找得到門。
- 結論：一句話講清楚在幾樓。

樓層有兩個來源，這支刻意兩個都算再對照：成大 GIS 直接回 floor，是官方資料；
教室代碼的規則（大樓代號後那一碼）是推算，GIS 查不到時才頂上。
兩邊不一致時不挑一個藏起來 —— 一律以 GIS 為準，但把差異講出來，
因為那通常代表代碼規則在這棟大樓不適用，使用者值得知道。
"""

from __future__ import annotations

from commute_agent.tools.floor_plan import describe_floor, get_floor_plan
from commute_agent.tools.ncku_geo import get_building_centroid
from commute_agent.tools.ncku_room import lookup_room
from commute_agent.tools.route_link import build_route_link


def _pick(candidates: list[dict]) -> dict | None:
    """完全相符的優先，沒有就退回第一筆模糊結果。"""
    exact = [c for c in candidates if c["exact_match"]]
    return exact[0] if exact else (candidates[0] if candidates else None)


def _conclusion(room: str, building: str, floor: str, floor_source: str) -> str:
    """一句話的結論。沒有樓層就照實說不知道，不要含糊帶過。"""
    where = building or "查不到大樓"
    if not floor:
        return f"{room} 在{where}，但查不到樓層資訊。"
    said = describe_floor(floor)
    if floor_source == "gis":
        return f"{room} 在{where} {said}。"
    if floor_source == "floor_plan":
        return f"{room} 在{where} {said}（依平面圖標示，成大 GIS 查不到這個代碼）。"
    return f"{room} 依教室代碼推算在{where} {said}（成大 GIS 查不到，這是推算值）。"


def locate_classroom(room_query: str, origin: str = "",
                     travel_mode: str = "walking") -> dict:
    """查一間教室在哪棟大樓、哪一層，並附上該樓層的平面圖與導航連結。

    適用時機：使用者問「這間教室在哪」、「在幾樓」、「教室怎麼走」，
    或要在畫面上標出教室平面圖時使用。

    Args:
        room_query: 教室代碼或名稱，例如 "4264"、"27103"、"格致廳小講堂"。
        origin: 導航起點。留空則產生不帶起點的連結。
        travel_mode: "walking"、"bicycling"、"driving" 或 "transit"。

    Returns:
        dict，包含：
        - status: "ok"、"not_found"（GIS 查無此教室）或 "error"
        - building_name、building_id: 實際所在大樓（以 GIS 為準）
        - floor、floor_source: 樓層，以及它的來源 —— "gis"（官方資料）、
          "floor_plan"（平面圖上的標示）或 "room_code"（由代碼推算）
        - floor_rule: 代碼推算規則的說明文字
        - floor_conflict: GIS 與代碼推算不一致時的說明，一致或無從比較時為 None
        - location: 大樓中心點座標（lat、lon）與 GIS 上的正式名稱
        - floor_plan: 該樓層的平面圖，status 為 "not_found" 代表還沒收錄這一層
        - route_link: 前往該大樓的導航連結
        - conclusion: 一句話結論，可直接顯示給使用者
    """
    query = (room_query or "").strip()
    if not query:
        return {"status": "error", "error_message": "沒有給教室代碼或名稱"}

    found = lookup_room(query)
    if found["status"] == "error":
        return {"status": "error", "room_query": query,
                "error_message": found.get("error_message", "教室查詢失敗")}

    chosen = _pick(found.get("candidates", []))
    building = chosen["building_name"] if chosen else ""
    room_code = (chosen["room_code"] if chosen else "") or query
    room_name = chosen["room_name"] if chosen else ""
    gis_floor = (chosen["floor"] if chosen else "") or ""

    plan = get_floor_plan(room_code, room_name or query, gis_floor)
    guessed = plan["floor_by_room_code"]

    floor = gis_floor or (guessed or "")
    floor_source = "gis" if gis_floor else ("room_code" if guessed else None)

    # GIS 查不到（像「格致廳小講堂」這種沒有代碼的場地），但平面圖對照表認得它時，
    # 就用圖上標的大樓與樓層 —— 有答案卻不講，比講一句「查不到」還糟
    if not building and plan["status"] == "ok":
        building = plan.get("plan_building", "")
        if not floor:
            floor, floor_source = plan["plan_floor"], "floor_plan"

    conflict = None
    if gis_floor and guessed and gis_floor.upper() != guessed.upper():
        # 代碼規則在這棟不適用。以 GIS 為準，但講出來——這是規則要補的例外
        conflict = (f"教室代碼推算是 {describe_floor(guessed)}，"
                    f"但成大 GIS 記的是 {describe_floor(gis_floor)}，以 GIS 為準。")

    # 有 build_id 就直接用代碼取座標：GIS 的名稱搜尋碰到「A006 唯農大樓」
    # 這種帶編號前綴的名字會對到別棟
    build_id = chosen["building_id"] if chosen else ""
    located = get_building_centroid(build_id) if build_id else {"status": "skipped"}
    target = ((located["lat"], located["lon"])
              if located.get("status") == "ok" and located.get("lat") is not None
              else (building or query))

    return {
        "status": "ok" if chosen else "not_found",
        "room_query": query,
        "room_code": room_code,
        "room_name": room_name,
        "building_name": building,
        "building_id": build_id,
        "exact_match_count": found["exact_match_count"],
        "floor": floor or None,
        "floor_source": floor_source,
        "floor_rule": plan["floor_rule"],
        "floor_conflict": conflict,
        "location": {"lat": located.get("lat"), "lon": located.get("lon"),
                     "name": located.get("name", ""),
                     "status": located.get("status")},
        "floor_plan": plan,
        "campus_map": plan["campus_map"],
        "route_link": build_route_link(target, origin=origin or None,
                                       travel_mode=travel_mode),
        "conclusion": _conclusion(room_code or query, building, floor, floor_source),
        "source": found["source"],
    }
