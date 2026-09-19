"""Tool 層：組出前往成大某地點的 Google Maps 導航連結（可選交通模式）。

原本只做步行（walking_link.py），加入停車場規劃後需要機車／汽車與大眾運輸，
因此改為通用的 build_route_link。

這種以地點名稱搜尋的連結不需要 Google Maps API 金鑰，也不會產生計費；
代價是精準度略遜於座標，而且拿不到預估時間——時間由 ncku_geo 另外估算。

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


def build_route_link(destination: str, origin: str | None = None,
                     travel_mode: str = "walking") -> str:
    """組出前往成大某棟大樓或地點的 Google Maps 導航連結。

    適用時機：已經知道目的地名稱（大樓或停車場）後，要給使用者一個
    可以直接點開的導航連結時使用。

    Args:
        destination: 目的地名稱，例如 "B501 資訊工程系館" 或 "奇美樓地下機車停車場"。
            大樓請用 lookup_room 回傳的 building_name，不要用課表上寫的名稱。
        origin: 起點名稱或地址。留空時 Google Maps 會使用使用者當下的定位。
        travel_mode: "walking"（步行）、"bicycling"（自行車）、
            "driving"（機車或開車）或 "transit"（大眾運輸）。

    Returns:
        Google Maps 導航連結字串。
    """
    destination = (destination or "").strip()
    if not destination:
        raise ValueError("destination 不可為空")
    if travel_mode not in TRAVEL_MODE_LABELS:
        raise ValueError(f"不支援的交通模式 {travel_mode!r}，"
                         f"可用選項：{list(TRAVEL_MODE_LABELS)}")

    params = {
        "api": "1",
        "destination": f"{NCKU_SUFFIX} {destination}",
        "travelmode": travel_mode,
    }
    origin = (origin or "").strip()
    if origin:
        params["origin"] = origin

    return f"https://www.google.com/maps/dir/?{urlencode(params)}"
