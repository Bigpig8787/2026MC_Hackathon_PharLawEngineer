"""Skill 層：把一趟 YouBike 行程拆成三段來估時間。

騎 YouBike 不是從家門口騎到教室門口，實際上是：

    走到借車站 → 騎到還車站 → 從還車站走到教室

只看騎乘時間會嚴重低估，兩段步行加起來常常比騎乘還久。

花錢的只有中間騎乘那段（Google 自行車路線，整趟一次）；兩段步行距離短，
用座標直線距離估就夠準，不值得為了幾百公尺再各打一次 API。
"""

from __future__ import annotations

from commute_agent.tools.geocode import geocode_place
from commute_agent.tools.ncku_geo import estimate_minutes, haversine_meters
from commute_agent.tools.route_link import build_route_link
from commute_agent.tools.travel_time import get_travel_time
from commute_agent.tools.youbike import fetch_stations


def find_station(stations: list[dict], name: str) -> dict | None:
    """依站名找站點。純函式，方便測試。"""
    target = (name or "").strip()
    for station in stations:
        if station["name"] == target:
            return station
    return None


def walk_leg(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> dict:
    """走路段一律用座標估算，不花錢。"""
    distance = haversine_meters(from_lat, from_lon, to_lat, to_lon)
    return {"minutes": estimate_minutes(distance, "walking"),
            "distance_m": round(distance), "is_estimate": True}


def plan_bike_journey(origin: str, destination: str,
                      from_station: str, to_station: str) -> dict:
    """估算「走到借車站 → 騎車 → 走到目的地」整趟要多久。

    適用時機：使用者選好了要在哪一站借車、哪一站還車之後，想知道整趟時間。

    Args:
        origin: 出發地名稱或地址。
        destination: 目的地，例如 "B501 資訊工程系館"。
        from_station: 借車站名稱，例如 "勝利國小(長榮路)"。
        to_station: 還車站名稱，例如 "大學長榮"。

    Returns:
        dict，包含：
        - status: "ok" 或 "error"
        - walk_to_station、ride、walk_to_destination: 三段各自的 minutes 與 distance_m
        - total_minutes: 三段相加；任一段算不出來時為 None
        - map_link: 串起兩個站點的 Google Maps 路線連結
    """
    start = geocode_place(origin)
    if start["status"] != "ok":
        return {"status": "error", "total_minutes": None,
                "error_message": f"查不到出發地「{origin}」的座標"}

    end = geocode_place(destination)
    if end["status"] != "ok":
        return {"status": "error", "total_minutes": None,
                "error_message": f"查不到目的地「{destination}」的座標"}

    try:
        stations = fetch_stations()
    except Exception as exc:  # noqa: BLE001 - fetch_stations 會包成自己的錯誤型別
        return {"status": "error", "total_minutes": None,
                "error_message": f"YouBike 站點查詢失敗：{exc}"}

    borrow = find_station(stations, from_station)
    give_back = find_station(stations, to_station)
    if borrow is None or give_back is None:
        missing = from_station if borrow is None else to_station
        return {"status": "error", "total_minutes": None,
                "error_message": f"找不到 YouBike 站「{missing}」"}

    walk_in = walk_leg(start["lat"], start["lon"], borrow["lat"], borrow["lon"])
    walk_out = walk_leg(give_back["lat"], give_back["lon"], end["lat"], end["lon"])

    # 騎乘段是整趟唯一花錢的地方，值得用 Google 的實際自行車路線
    ride = get_travel_time((borrow["lat"], borrow["lon"]),
                           (give_back["lat"], give_back["lon"]),
                           "bicycling", provider="google")
    ride_minutes = ride.get("minutes") if ride["status"] == "ok" else None

    legs = [walk_in["minutes"], ride_minutes, walk_out["minutes"]]
    total = sum(legs) if all(m is not None for m in legs) else None

    return {
        "status": "ok",
        "origin": origin,
        "destination": end["name"] or destination,
        "from_station": {"name": borrow["name"], "bikes": borrow["bikes"]},
        "to_station": {"name": give_back["name"], "docks": give_back["docks"]},
        "walk_to_station": walk_in,
        "ride": {"minutes": ride_minutes, "distance_m": ride.get("distance_m"),
                 "provider": ride.get("provider"),
                 "is_estimate": ride.get("is_estimate", True),
                 "unavailable_reason": ride.get("reason") if ride["status"] != "ok" else None},
        "walk_to_destination": walk_out,
        "total_minutes": total,
        "map_link": build_route_link(
            end["name"] or destination, origin=origin, travel_mode="bicycling",
            waypoints=[borrow["name"], give_back["name"]]),
        "note": ("走路段為直線距離估算，騎乘段"
                 + ("來自 Google 實際路線。" if not ride.get("is_estimate", True)
                    else "亦為估算值。")),
    }
