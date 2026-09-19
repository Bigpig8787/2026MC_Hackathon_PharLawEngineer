"""Tool 層：組出前往成大某棟大樓的 Google Maps 步行導航連結。

備註：成大地理資訊系統的 buildinfo.htm 只回傳大樓名稱與代碼，不含經緯度
（已於 2026-09-19 實測確認），因此改用 Google Maps 的地點名稱搜尋式導航連結。
這種連結不需要 Google Maps API 金鑰；缺點是精準度略遜於座標，
待 Google Maps API 金鑰申請後可換成 Places API 查精確座標升級。

本檔為純函式，不打任何網路、不讀取設定，符合「Tool 不呼叫任何東西」原則
中最單純的一種：連外部服務都不呼叫。
"""

from __future__ import annotations

from urllib.parse import urlencode

NCKU_SUFFIX = "國立成功大學"


def build_walking_link(building_name: str, origin: str | None = None) -> str:
    """組出前往成大某棟大樓的 Google Maps 步行導航連結。

    適用時機：已經用 lookup_room 查到教室所在的大樓名稱後，
    需要給使用者一個可以直接點開走去的導航連結時使用。

    Args:
        building_name: 大樓名稱，例如 "B502 資訊工程系大樓"（來自 lookup_room
            回傳的 building_name 欄位，不要用課表上寫的大樓名稱，兩者可能不同）。
        origin: 起點名稱或地址，例如 "敬業一舍"。留空時 Google Maps 會使用
            使用者當下的定位作為起點。

    Returns:
        Google Maps 步行導航連結字串，使用者點擊後會在 Google Maps
        App 或網頁開啟導航。
    """
    building_name = (building_name or "").strip()
    if not building_name:
        raise ValueError("building_name 不可為空")

    params = {
        "api": "1",
        "destination": f"{NCKU_SUFFIX} {building_name}",
        "travelmode": "walking",
    }
    origin = (origin or "").strip()
    if origin:
        params["origin"] = origin

    return f"https://www.google.com/maps/dir/?{urlencode(params)}"
