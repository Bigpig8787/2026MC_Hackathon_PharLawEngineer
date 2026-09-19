"""Tool 層：中央氣象署自動雨量站的即時觀測（需要免費的 CWA_API_KEY，與天氣預報同一把）。

weather.py 給的是「預報」（每三小時一段的降雨機率），回答不了「現在到底有沒有在下」。
這支查 O-A0002-001（雨量觀測資料）：全台一千多個雨量站，每十分鐘更新，
取離成大最近、而且真的有資料的那個站。

雨量站回傳負數（例如 -998）代表缺測或儀器故障，不是「下負的雨」，一律當沒有資料，
不能拿來當 0 —— 沒有資料跟「沒下雨」是兩回事。
"""

from __future__ import annotations

import time

import requests

from api import load_settings
from commute_agent.scenario import simulated
from commute_agent.tools.ncku_geo import haversine_meters
from commute_agent.tools.weather import _get_with_ssl_fallback

DATASET = "O-A0002-001"
ENDPOINT = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

# 成大光復校區中心附近
NCKU_LAT, NCKU_LON = 22.9968, 120.2168

# 資料約每 10 分鐘更新，全台一千多站一次下載要幾 MB，快取 5 分鐘足夠
CACHE_TTL_SECONDS = 300

# 超過這個距離的雨量站不能代表成大，寧可說查不到
MAX_STATION_KM = 8.0

# 過去一小時累積雨量達這個值算大雨。這是我們自己訂的門檻，不是氣象署的官方分級
HEAVY_1HR_MM = 10.0

_cache: dict = {"fetched_at": 0.0, "stations": []}


class RainError(RuntimeError):
    """雨量觀測回應無法使用。"""


def _number(value) -> float | None:
    """雨量數字；缺測（負數）或無法解析都回 None。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _wgs84(station: dict) -> tuple[float, float] | None:
    for coord in (station.get("GeoInfo") or {}).get("Coordinates") or []:
        if coord.get("CoordinateName") == "WGS84":
            try:
                return float(coord["StationLatitude"]), float(coord["StationLongitude"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _mm(element: dict | None, key: str) -> float | None:
    return _number(((element or {}).get(key) or {}).get("Precipitation"))


def parse_stations(payload: dict) -> list[dict]:
    """把氣象署回應整理成統一格式，座標缺漏的站直接略過。"""
    rows = (payload.get("records") or {}).get("Station") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RainError("回應缺少 records.Station 陣列")

    stations = []
    for row in rows:
        coords = _wgs84(row)
        if coords is None:
            continue
        rainfall = row.get("RainfallElement") or {}
        geo = row.get("GeoInfo") or {}
        stations.append({
            "name": row.get("StationName", ""),
            "id": row.get("StationId", ""),
            "county": geo.get("CountyName", ""),
            "town": geo.get("TownName", ""),
            "lat": coords[0],
            "lon": coords[1],
            "obs_time": (row.get("ObsTime") or {}).get("DateTime", ""),
            "now_mm": _mm(rainfall, "Now"),
            "past10min_mm": _mm(rainfall, "Past10Min"),
            "past1hr_mm": _mm(rainfall, "Past1hr"),
        })
    return stations


def nearest_stations(stations: list[dict], lat: float, lon: float,
                     max_km: float = MAX_STATION_KM, limit: int = 3) -> list[dict]:
    """離指定位置最近、而且「現在」或「過去 10 分鐘」有讀數的雨量站。純函式。"""
    found = []
    for station in stations:
        if station["now_mm"] is None and station["past10min_mm"] is None:
            continue
        km = haversine_meters(lat, lon, station["lat"], station["lon"]) / 1000
        if km <= max_km:
            found.append((km, station))
    found.sort(key=lambda pair: pair[0])
    return [{**station, "distance_km": round(km, 1)} for km, station in found[:limit]]


def classify(now_mm: float | None, past10min_mm: float | None,
             past1hr_mm: float | None) -> tuple[bool, str]:
    """回傳 (現在有沒有在下, 過去一小時的雨勢)。

    is_raining 看的是當下：現在或過去 10 分鐘有雨。
    level 看的是過去一小時累積量："none" 沒雨、"light" 有雨但不大、"heavy" 達大雨門檻——
    所以雨剛停時 is_raining 是 False，level 仍可能是 heavy，路面還是濕的。
    """
    is_raining = any(v is not None and v > 0 for v in (now_mm, past10min_mm))
    hour = past1hr_mm or 0.0
    if hour >= HEAVY_1HR_MM:
        level = "heavy"
    elif is_raining or hour > 0:
        level = "light"
    else:
        level = "none"
    return is_raining, level


def _fetch_stations(settings) -> list[dict]:
    now = time.monotonic()
    if _cache["stations"] and now - _cache["fetched_at"] < CACHE_TTL_SECONDS:
        return _cache["stations"]

    resp = _get_with_ssl_fallback(
        f"{ENDPOINT}/{DATASET}",
        params={"Authorization": settings.cwa_api_key, "format": "JSON"},
        timeout=max(settings.http_timeout_seconds, 30),
        headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        raise RainError(f"中央氣象署回應 HTTP {resp.status_code}")
    stations = parse_stations(resp.json())
    _cache.update(fetched_at=now, stations=stations)
    return stations


@simulated("rain_now")
def get_rain_now(lat: float = NCKU_LAT, lon: float = NCKU_LON) -> dict:
    """查成大附近雨量站「現在有沒有在下雨」（實測，不是預報）。

    適用時機：使用者問「現在在下雨嗎」，或要判斷剛出門會不會淋到雨時。
    天氣預報是每三小時一段的機率，這支是雨量站每十分鐘更新的實際讀數。

    Args:
        lat、lon: 要查的位置，預設是成大光復校區。

    Returns:
        dict，包含：
        - status: "ok"、"not_found"（附近沒有雨量站有讀數）或 "error"
        - is_raining: 現在或過去 10 分鐘有雨
        - level: 過去一小時雨勢，"none"／"light"／"heavy"
        - now_mm、past10min_mm、past1hr_mm: 各時段雨量（毫米），缺測為 None
        - station: 使用的雨量站，含 name、distance_km、obs_time
    """
    settings = load_settings()
    result = {"status": "ok", "station": None, "is_raining": False, "level": "none",
              "now_mm": None, "past10min_mm": None, "past1hr_mm": None}

    if not settings.cwa_api_key:
        return {**result, "status": "error", "error_message": "未設定 CWA_API_KEY"}

    try:
        stations = _fetch_stations(settings)
    except requests.Timeout:
        return {**result, "status": "error", "error_message": "中央氣象署查詢逾時"}
    except requests.RequestException as exc:
        return {**result, "status": "error",
                "error_message": f"無法連線中央氣象署（{type(exc).__name__}）"}
    except (RainError, ValueError) as exc:
        return {**result, "status": "error", "error_message": f"回應格式異常：{exc}"}

    nearby = nearest_stations(stations, lat, lon, limit=1)
    if not nearby:
        return {**result, "status": "not_found",
                "note": f"{MAX_STATION_KM:g} 公里內沒有雨量站有讀數"}

    station = nearby[0]
    is_raining, level = classify(station["now_mm"], station["past10min_mm"],
                                 station["past1hr_mm"])
    return {**result,
            "station": {"name": station["name"], "distance_km": station["distance_km"],
                        "obs_time": station["obs_time"]},
            "is_raining": is_raining, "level": level,
            "now_mm": station["now_mm"], "past10min_mm": station["past10min_mm"],
            "past1hr_mm": station["past1hr_mm"],
            "note": "中央氣象署自動雨量站實測，約每 10 分鐘更新。"}
