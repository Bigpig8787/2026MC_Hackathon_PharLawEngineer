"""Tool 層：TDX 臺南市公車即時到站（需要免費的 TDX_CLIENT_ID／SECRET）。

TDX 走 OAuth2 client_credentials，token 有效 24 小時，所以在記憶體裡快取，
不要每次查公車都去換一次 token。

到站時間的 EstimateTime 單位是秒，而且可能是 None——公車還沒發車、
末班already過站、或該路線當下沒有車在跑時都會是 None。這種情況要照實說
「目前沒有班次資訊」，不能當成 0 分鐘進站。
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from api import load_settings
from commute_agent.tools.geocode import geocode_place
from commute_agent.tools.ncku_geo import haversine_meters

TOKEN_URL = ("https://tdx.transportdata.tw/auth/realms/TDXConnect"
             "/protocol/openid-connect/token")
API_BASE = "https://tdx.transportdata.tw/api/basic/v2/Bus"
CITY = "Tainan"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

DEFAULT_RADIUS_M = 400
# 到站查詢要把站牌 UID 串成 OData 條件，取最近幾個就夠，太多會撐爆查詢字串
MAX_STOPS_PER_QUERY = 6
# token 實際有效 24 小時，提早 5 分鐘換避免邊界時失敗
TOKEN_SAFETY_MARGIN = 300

# StopStatus：0 才是正常可預期到站，其餘代表未發車、末班已過或交管
STOP_STATUS_NORMAL = 0

_token_cache: dict = {"token": "", "expires_at": 0.0}


class TDXError(RuntimeError):
    """TDX 回應無法使用。"""


def _get_token(settings) -> str:
    now = time.monotonic()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials",
              "client_id": settings.tdx_client_id,
              "client_secret": settings.tdx_client_secret},
        timeout=max(settings.http_timeout_seconds, 20),
        headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        raise TDXError(f"TDX 取得 token 失敗（HTTP {resp.status_code}）")
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise TDXError("TDX 回應沒有 access_token")
    _token_cache.update(
        token=token,
        expires_at=now + max(60, int(payload.get("expires_in", 86400)) - TOKEN_SAFETY_MARGIN))
    return token


def _api_get(path: str, params: dict, settings) -> list:
    resp = requests.get(f"{API_BASE}/{path}", params={**params, "$format": "JSON"},
                        headers={"authorization": f"Bearer {_get_token(settings)}",
                                 "User-Agent": USER_AGENT},
                        timeout=max(settings.http_timeout_seconds, 20))
    # TDX 免費方案的速率限制很緊，測試時很容易撞到，訊息要講清楚而不是丟 HTTP 429
    if resp.status_code == 429:
        raise TDXError("TDX 速率限制已達上限，請稍後再查")
    if resp.status_code != 200:
        raise TDXError(f"TDX 回應 HTTP {resp.status_code}")
    rows = resp.json()
    if not isinstance(rows, list):
        raise TDXError("TDX 回應不是陣列")
    return rows


def parse_arrivals(rows: list, stop_uids: set[str]) -> list[dict]:
    """把到站預估整理成清單，只留指定站牌、而且真的有班次的。

    EstimateTime 為 None 代表沒有車在跑，照實濾掉比顯示「0 分鐘」誠實。
    """
    arrivals = []
    for row in rows:
        if row.get("StopUID") not in stop_uids:
            continue
        seconds = row.get("EstimateTime")
        if seconds is None or row.get("StopStatus") != STOP_STATUS_NORMAL:
            continue
        arrivals.append({
            "route": row.get("RouteName", {}).get("Zh_tw", ""),
            "stop": row.get("StopName", {}).get("Zh_tw", ""),
            "stop_uid": row.get("StopUID"),
            "minutes": max(0, round(int(seconds) / 60)),
            "direction": row.get("Direction"),
        })
    arrivals.sort(key=lambda a: a["minutes"])
    return arrivals


def parse_stops(rows: list, lat: float, lon: float) -> list[dict]:
    """整理附近站牌並補上與查詢點的距離。"""
    stops = []
    for row in rows:
        position = row.get("StopPosition") or {}
        stop_lat, stop_lon = position.get("PositionLat"), position.get("PositionLon")
        if stop_lat is None or stop_lon is None:
            continue
        distance = haversine_meters(lat, lon, float(stop_lat), float(stop_lon))
        stops.append({
            "name": row.get("StopName", {}).get("Zh_tw", ""),
            "stop_uid": row.get("StopUID", ""),
            "distance_m": round(distance),
            "walk_minutes": max(1, round(distance / 80)),
        })
    stops.sort(key=lambda s: s["distance_m"])
    return stops


def unique_by_name(stops: list[dict]) -> list[dict]:
    """同一個站名常有多個 UID（不同方向、對街的站牌），顯示時只留最近的那個。

    查到站時間仍要用全部的 UID，否則會漏掉對向的班次。
    """
    seen: dict[str, dict] = {}
    for stop in stops:
        if stop["name"] not in seen:
            seen[stop["name"]] = stop
    return list(seen.values())


def get_bus_eta(place: str, radius_m: int = DEFAULT_RADIUS_M) -> dict:
    """查某個地點附近公車站牌的即時到站時間。

    適用時機：使用者想搭公車，或下雨天騎車不方便、需要改搭公車時使用。

    Args:
        place: 地點名稱，例如 "成大圖書館"、"B501 資訊工程系館"。
        radius_m: 搜尋半徑（公尺），預設 400。

    Returns:
        dict，包含：
        - status: "ok"、"not_found"（附近沒有站牌或目前沒有班次）或 "error"
        - stops: 附近站牌清單，含 name、distance_m、walk_minutes
        - arrivals: 即將到站的班次，依剩餘分鐘排序，含 route、stop、minutes
        - place_name: 實際用來定位的地點名稱

    注意：arrivals 為空代表目前這些站牌都沒有車在跑（例如深夜或末班已過），
    不是查詢失敗，要照實告訴使用者，不要說「馬上到」。
    """
    settings = load_settings()
    tz = settings.timezone
    result = {"status": "ok", "place_name": place, "stops": [], "arrivals": [],
              "fetched_at": datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds")}

    if not (settings.tdx_client_id and settings.tdx_client_secret):
        return {**result, "status": "error",
                "error_message": "未設定 TDX_CLIENT_ID／TDX_CLIENT_SECRET"}

    # 同 YouBike：校外地址要靠 Google 解析才找得到附近站牌
    found = geocode_place(place)
    if found["status"] != "ok":
        return {**result, "status": "error",
                "error_message": f"查不到「{place}」的座標，無法找附近公車站"}
    result["place_name"] = found["name"]

    spatial = f"nearby({found['lat']},{found['lon']},{radius_m})"
    try:
        stop_rows = _api_get(f"Stop/City/{CITY}", {"$spatialFilter": spatial, "$top": 30},
                             settings)
        stops = parse_stops(stop_rows, found["lat"], found["lon"])
        if not stops:
            return {**result, "status": "not_found",
                    "note": f"{radius_m} 公尺內沒有公車站牌"}

        # 到站預估不支援 nearby（TDX 會回 500：BusN1EstimateTime is not supported
        # to search nearby method），所以改用剛查到的站牌 UID 逐一過濾。
        # 站牌取最近幾個就好，UID 太多會把查詢字串撐爆，也更容易撞速率限制。
        nearest = stops[:MAX_STOPS_PER_QUERY]
        uid_filter = " or ".join(f"StopUID eq '{s['stop_uid']}'" for s in nearest)
        eta_rows = _api_get(f"EstimatedTimeOfArrival/City/{CITY}",
                            {"$filter": uid_filter, "$top": 200}, settings)
        arrivals = parse_arrivals(eta_rows, {s["stop_uid"] for s in nearest})
    except requests.Timeout:
        return {**result, "status": "error", "error_message": "TDX 查詢逾時"}
    except requests.RequestException as exc:
        return {**result, "status": "error",
                "error_message": f"無法連線 TDX（{type(exc).__name__}）"}
    except (TDXError, ValueError) as exc:
        return {**result, "status": "error", "error_message": str(exc)}

    return {**result,
            "status": "ok" if arrivals else "not_found",
            "stops": unique_by_name(stops)[:5],
            "arrivals": arrivals[:8],
            "note": "" if arrivals else "附近站牌目前沒有班次資訊（可能已過末班或尚未發車）"}
