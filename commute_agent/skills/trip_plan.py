"""Skill 層：估算從某個起點到某個目的地要走多久，並附上導航連結。

時間本身不在這裡算，而是交給 tools/travel_time.py 的統一接口：
設定成 estimate 就用成大 GIS 座標估算（免費，但只涵蓋校內地點），
設定成 google 就用 Google Routes API 拿真實路線時間（需金鑰、會計費，
但校外地址也算得出來）。Google 失敗時接口會自動退回估算。

不論哪個來源，算不出來就明講算不出來，不拿附近大樓的座標充數。
"""

from __future__ import annotations

from commute_agent.tools.geocode import geocode_place
from commute_agent.tools.route_link import TRAVEL_MODE_LABELS, build_route_link
from commute_agent.tools.travel_time import get_travel_time

PROVIDER_LABELS = {
    "estimate": "直線距離估算",
    "google_routes": "Google 實際路線",
}


def estimate_trip(origin: str, destination: str, travel_mode: str = "walking") -> dict:
    """估算從起點到目的地的距離與所需時間，並給出導航連結。

    適用時機：使用者說了自己在哪裡（例如「我在圖書館」），想知道去某棟大樓
    要走多久時使用。

    Args:
        origin: 起點名稱，例如 "圖書館"、"成大圖書館"，或校外地址。
        destination: 目的地名稱，例如 "B501 資訊工程系館"。
        travel_mode: "walking"、"bicycling"、"driving" 或 "transit"。

    Returns:
        dict，包含：
        - status: "ok" 或 "error"
        - can_estimate: 是否算得出時間。為 False 時 minutes 為 None，
          此時要如實告訴使用者算不出來，不可以自己編一個數字
        - distance_m、minutes: 距離與時間
        - is_estimate: True 代表是估算值，轉述時要說「大約」；
          False 代表來自 Google 的實際路線時間
        - provider_label: 時間來源的中文說明，可直接顯示給使用者
        - route_link: Google Maps 導航連結，即使算不出時間也一定可用
        - note: 資料來源與限制說明
    """
    if travel_mode not in TRAVEL_MODE_LABELS:
        return {"status": "error", "can_estimate": False,
                "error_message": f"不支援的交通模式 {travel_mode!r}"}

    timing = get_travel_time(origin, destination, travel_mode)
    # 連結也用座標，跟時間計算走同一份定位，避免「算的是這棟、導到那棟」
    located = geocode_place(destination)
    link_target = ((located["lat"], located["lon"]) if located["status"] == "ok"
                   else destination)
    result = {
        "status": "ok",
        "origin": origin,
        "destination": destination,
        "travel_mode": travel_mode,
        "travel_mode_label": TRAVEL_MODE_LABELS[travel_mode],
        "distance_m": timing.get("distance_m"),
        "minutes": timing.get("minutes"),
        "can_estimate": timing["status"] == "ok" and timing.get("minutes") is not None,
        "is_estimate": timing.get("is_estimate", True),
        "provider": timing.get("provider", "estimate"),
        "provider_label": PROVIDER_LABELS.get(timing.get("provider", ""), "未知來源"),
        "unresolved": timing.get("unresolved"),
        "origin_name": timing.get("origin_name") or origin,
        "destination_name": timing.get("destination_name") or destination,
        "route_link": build_route_link(link_target, origin=origin or None,
                                       travel_mode=travel_mode),
    }

    notes = []
    if timing.get("fallback_reason"):
        notes.append(f"Google 路線查詢失敗（{timing['fallback_reason']}），已改用估算值。")
    if result["can_estimate"]:
        notes.append("時間為估算值，不含紅綠燈與實際路網。"
                     if result["is_estimate"] else "時間來自 Google 實際路線規劃。")
    else:
        notes.append(timing.get("reason", "無法取得時間。"))
    result["note"] = "".join(notes)
    return result


def plan_ride_and_walk(origin: str, destination_building: str,
                       vehicle_type: str = "機車") -> dict:
    """騎車或開車去上課時，把「騎到停車場」和「從停車場走到教室」分開算。

    適用時機：使用者說要騎機車或開車去某棟大樓時使用。單純步行或大眾運輸
    請改用 estimate_trip。

    為什麼要拆兩段：Google 只會算到目的地大樓門口的騎車時間，忽略實際上
    得先停車再走過去的那段。拆開算才貼近真實，而且只有騎車那段需要花錢
    呼叫 Google（整趟只打一次），停車場走到教室是用成大 GIS 座標免費估的。

    Args:
        origin: 出發地，校內地點或校外地址皆可。
        destination_building: 目的地大樓，例如 "B501 資訊工程系館"。
        vehicle_type: "機車" 或 "汽車"。

    Returns:
        dict，包含：
        - status: "ok" 或 "error"
        - lot: 建議停的停車場，含 name、campus、available
        - ride: 騎車段，含 minutes、distance_m、provider、is_estimate
        - walk: 停車場走到教室那段，含 minutes、distance_m（一律為 GIS 估算）
        - total_minutes: 兩段相加；任一段算不出來時為 None
        - note: 各段來源與限制說明
    """
    from commute_agent.skills.parking_plan import load_lot_locations, plan_parking

    parking = plan_parking(destination_building, vehicle_type)
    if parking["status"] != "ok" or not parking.get("recommended"):
        return {"status": "error", "lot": None, "ride": None, "walk": None,
                "total_minutes": None,
                "error_message": parking.get("error_message")
                or f"找不到剩餘車位足夠的{vehicle_type}停車場"}

    lot = parking["recommended"]

    # Google 不認得「三系館地下機車停車場」這種名稱，改送座標最準。
    # 座標來自免費反查 GIS 建好的對照表，這裡直接沿用，不額外花錢。
    known = load_lot_locations().get(lot["name"], {})
    ride_destination = ((known["lat"], known["lon"])
                        if known.get("lat") is not None else lot["name"])

    # 騎車段是整趟唯一呼叫 Google 的地方，而且明確指定來源：
    # 全域設定維持 estimate 讓純步行不花錢，只有這段值得付費換真實路網時間。
    ride = get_travel_time(origin, ride_destination, "driving", provider="google")
    # 走路段：plan_parking 已經用 GIS 座標算過，直接沿用，不再打任何 API
    walk = {"minutes": lot["minutes"], "distance_m": lot["distance_m"],
            "provider": "estimate", "is_estimate": True}

    total = (ride["minutes"] + walk["minutes"]
             if ride["status"] == "ok" and ride.get("minutes") is not None
             and walk["minutes"] is not None else None)

    notes = [f"騎車段由{PROVIDER_LABELS.get(ride.get('provider'), '未知來源')}提供"]
    if ride.get("fallback_reason"):
        notes.append(f"（Google 查詢失敗：{ride['fallback_reason']}）")
    notes.append("；停車場走到教室為成大 GIS 直線距離估算。")

    return {
        "status": "ok",
        "origin": origin,
        "destination": destination_building,
        "vehicle_type": vehicle_type,
        "lot": {"name": lot["name"], "campus": lot["campus"],
                "available": lot["available"]},
        "ride": {"minutes": ride.get("minutes"), "distance_m": ride.get("distance_m"),
                 "provider": ride.get("provider"), "is_estimate": ride.get("is_estimate"),
                 "unavailable_reason": ride.get("reason") if ride["status"] != "ok" else None},
        "walk": walk,
        "total_minutes": total,
        "skipped_full": parking["skipped_full"],
        "note": "".join(notes),
    }
