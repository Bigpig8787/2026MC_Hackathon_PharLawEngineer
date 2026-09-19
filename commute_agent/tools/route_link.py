"""Tool 層：組出前往成大某地點的 Google Maps 導航連結（可選交通模式）。

起訖點與途經點都可以給座標或名稱，**有座標就一定要給座標**：
Google 對地名是模糊比對，成大的大樓名稱帶編號前綴（例如「B406 三系館鋼構區」）
時常對到隔壁棟，實測就曾被解析成材料系館；YouBike 站名如「勝利國小(長榮路)」
更是全台可能重複。座標沒有這個問題，而且我們在算距離時本來就查過了。

只有真的沒有座標時才退回名稱，這時會補上校名以降低（但無法消除）誤判機率。

這種連結不需要 Google Maps API 金鑰，也不會產生計費。
本檔為純函式，不打任何網路、不讀取設定。
"""

from __future__ import annotations

from urllib.parse import urlencode

NCKU_SUFFIX = "國立成功大學"

# Google Maps 的 travelmode 參數值 → 中文標籤
TRAVEL_MODE_LABELS = {
    "walking": "步行",
    "bicycling": "自行車",
    "driving": "機車／開車",
    "transit": "大眾運輸",
}

Place = "str | tuple[float, float] | list"


def format_place(place, add_campus_prefix: bool = True) -> str:
    """把地點轉成 Google Maps 認得的字串。

    座標格式化成 "緯度,經度"，Google 會直接落在那個點，不做任何猜測。
    名稱則補上校名，讓「資訊系館」不會導到別的學校。
    """
    if isinstance(place, (tuple, list)):
        lat, lon = place
        return f"{float(lat)},{float(lon)}"
    text = str(place or "").strip()
    if not text:
        return ""
    if not add_campus_prefix or text.startswith(NCKU_SUFFIX):
        return text
    return f"{NCKU_SUFFIX} {text}"


def build_route_link(destination, origin=None, travel_mode: str = "walking",
                     waypoints: list | None = None) -> str:
    """組出前往成大某棟大樓或地點的 Google Maps 導航連結。

    適用時機：已經知道目的地後，要給使用者一個可以直接點開的導航連結時使用。

    Args:
        destination: 目的地。優先給 (緯度, 經度) 座標；沒有座標時才給名稱，
            例如 "B501 資訊工程系館"（請用 lookup_room 回傳的 building_name）。
        origin: 起點，同樣優先給座標。留空時 Google Maps 會使用使用者當下定位。
        travel_mode: "walking"（步行）、"bicycling"（自行車）、
            "driving"（機車或開車）或 "transit"（大眾運輸）。
        waypoints: 中途必經的地點（例如 YouBike 的借車站與還車站），
            一樣可以混用座標與名稱，Google Maps 會照順序串成一條路線。

    Returns:
        Google Maps 導航連結字串。
    """
    if travel_mode not in TRAVEL_MODE_LABELS:
        raise ValueError(f"不支援的交通模式 {travel_mode!r}，"
                         f"可用選項：{list(TRAVEL_MODE_LABELS)}")

    target = format_place(destination)
    if not target:
        raise ValueError("destination 不可為空")

    params = {"api": "1", "destination": target, "travelmode": travel_mode}

    # 起點常是校外住家地址，補校名反而會害它找不到
    start = format_place(origin, add_campus_prefix=False) if origin else ""
    if start:
        params["origin"] = start

    stops = [format_place(w) for w in (waypoints or [])]
    stops = [w for w in stops if w]
    if stops:
        # Google Maps 的 waypoints 以 | 分隔，urlencode 會自動轉成 %7C
        params["waypoints"] = "|".join(stops)

    return f"https://www.google.com/maps/dir/?{urlencode(params)}"
