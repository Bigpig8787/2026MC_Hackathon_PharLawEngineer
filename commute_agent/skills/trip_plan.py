"""Skill 層：估算從某個起點到某個目的地要走多久，並附上導航連結。

距離來自成大 GIS 的大樓座標，因此只有「校內地點 → 校內地點」估得出時間。
起點若是校外地址（例如住家或火車站），GIS 查不到座標，這裡會明確回報
can_estimate=False，而不是拿附近的大樓充數——寧可說不知道，也不要給錯的時間。
"""

from __future__ import annotations

from commute_agent.tools.ncku_geo import (
    DETOUR_FACTOR,
    estimate_minutes,
    haversine_meters,
    resolve_place,
)
from commute_agent.tools.route_link import TRAVEL_MODE_LABELS, build_route_link


def estimate_trip(origin: str, destination: str, travel_mode: str = "walking") -> dict:
    """估算從起點到目的地的距離與所需時間，並給出導航連結。

    適用時機：使用者說了自己在哪裡（例如「我在圖書館」），想知道去某棟大樓
    要走多久時使用。起點與目的地都必須是成大校內地點才估得出時間。

    Args:
        origin: 起點名稱，例如 "圖書館"、"成大圖書館"、"雲平大樓"。
        destination: 目的地名稱，例如 "B501 資訊工程系館"。
        travel_mode: "walking"、"bicycling"、"driving" 或 "transit"。

    Returns:
        dict，包含：
        - status: "ok" 或 "error"
        - can_estimate: 是否算得出「時間」。起點或目的地不在成大 GIS 裡時為 False；
          大眾運輸即使兩端都查得到也是 False（有距離但無法估時間）
        - distance_m: 兩點直線距離（公尺）
        - minutes: 估算分鐘數。大眾運輸一律為 None，因為受班次影響太大
        - unresolved: 查不到座標的那一端（"origin"、"destination" 或 None）
        - route_link: Google Maps 導航連結
        - note: 說明這是估算值
    """
    if travel_mode not in TRAVEL_MODE_LABELS:
        return {"status": "error", "can_estimate": False,
                "error_message": f"不支援的交通模式 {travel_mode!r}"}

    result = {
        "status": "ok",
        "origin": origin,
        "destination": destination,
        "travel_mode": travel_mode,
        "travel_mode_label": TRAVEL_MODE_LABELS[travel_mode],
        "distance_m": None,
        "minutes": None,
        "can_estimate": False,
        "unresolved": None,
        "route_link": build_route_link(destination, origin=origin or None,
                                       travel_mode=travel_mode),
    }

    start, end = resolve_place(origin), resolve_place(destination)
    if start["status"] != "ok":
        result["unresolved"] = "origin"
        result["note"] = (f"起點「{origin}」不在成大地理資訊系統裡（可能是校外地址），"
                          "無法估算距離與時間，但導航連結仍可使用。")
        return result
    if end["status"] != "ok":
        result["unresolved"] = "destination"
        result["note"] = f"目的地「{destination}」查不到座標，無法估算距離與時間。"
        return result

    distance = haversine_meters(start["lat"], start["lon"], end["lat"], end["lon"])
    minutes = estimate_minutes(distance, travel_mode)
    result.update(
        origin_name=start["name"], destination_name=end["name"],
        distance_m=round(distance),
        minutes=minutes,
        # 大眾運輸算得出距離卻估不出時間，所以旗標跟著時間走，介面才不會顯示「約 None 分」
        can_estimate=minutes is not None,
    )
    result["note"] = (
        f"距離為直線距離乘上 {DETOUR_FACTOR} 倍繞路係數後估算，不含紅綠燈與實際路網。"
        if travel_mode not in ("transit",) else
        "大眾運輸受班次影響過大，不提供時間估算。"
    )
    return result
