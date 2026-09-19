"""Tool 層：YouBike 2.0 即時站點資訊（免金鑰）。

官方端點一次回傳全台 9500 多站、約 6 MB，所以這裡做了短時間快取：
資料本身大約每分鐘更新一次，重複抓沒有意義，還會拖慢每次查詢。

借車看 available_spaces（可借車輛數），還車看 empty_spaces（可停空位）——
這兩件事需要的是相反的東西，站點快滿時對還車的人是壞消息、對借車的人不是。
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from api import load_settings
from commute_agent.tools.ncku_geo import haversine_meters, resolve_place

STATIONS_URL = "https://apis.youbike.com.tw/json/station-yb2.json"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

# 官方資料約每分鐘更新，快取這麼久不會看到過期車位，又能避免重複下載 6 MB
CACHE_TTL_SECONDS = 60

# 只留台南市範圍，全台資料留在記憶體裡沒有意義
TAINAN_BOUNDS = {"lat_min": 22.85, "lat_max": 23.15,
                 "lon_min": 120.05, "lon_max": 120.40}

DEFAULT_RADIUS_M = 600

_cache: dict = {"fetched_at": 0.0, "stations": []}


class YouBikeError(RuntimeError):
    """YouBike 端點回應無法使用。"""


def parse_stations(payload: list, bounds: dict = TAINAN_BOUNDS) -> list[dict]:
    """把官方回應轉成統一格式，並只留指定範圍內、狀態正常的站點。"""
    if not isinstance(payload, list):
        raise YouBikeError("回應不是站點陣列")

    stations = []
    for row in payload:
        try:
            lat, lon = float(row["lat"]), float(row["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (bounds["lat_min"] <= lat <= bounds["lat_max"]
                and bounds["lon_min"] <= lon <= bounds["lon_max"]):
            continue
        # status 非 1 代表停用或維護中，顯示出來只會讓使用者白跑一趟
        if row.get("status") != 1:
            continue
        stations.append({
            "name": row.get("name_tw", ""),
            "address": row.get("address_tw", ""),
            "lat": lat,
            "lon": lon,
            "bikes": int(row.get("available_spaces") or 0),
            "docks": int(row.get("empty_spaces") or 0),
            "capacity": int(row.get("parking_spaces") or 0),
            "updated_at": row.get("updated_at", ""),
        })
    return stations


def fetch_stations(force: bool = False) -> list[dict]:
    """抓站點資料，預設沿用快取。"""
    now = time.monotonic()
    if not force and _cache["stations"] and now - _cache["fetched_at"] < CACHE_TTL_SECONDS:
        return _cache["stations"]

    settings = load_settings()
    resp = requests.get(STATIONS_URL, timeout=max(settings.http_timeout_seconds, 20),
                        headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        raise YouBikeError(f"YouBike 回應 HTTP {resp.status_code}")
    stations = parse_stations(resp.json())
    _cache.update(fetched_at=now, stations=stations)
    return stations


def nearby_stations(stations: list[dict], lat: float, lon: float, need: str = "bike",
                    radius_m: float = DEFAULT_RADIUS_M, limit: int = 5) -> list[dict]:
    """找出附近可用的站點並依距離排序。純函式。

    need="bike" 時只留借得到車的站，need="dock" 時只留還得了車的站。
    """
    key = "bikes" if need == "bike" else "docks"
    found = []
    for station in stations:
        distance = haversine_meters(lat, lon, station["lat"], station["lon"])
        if distance > radius_m or station[key] <= 0:
            continue
        found.append({**station, "distance_m": round(distance),
                      "walk_minutes": max(1, round(distance / 80))})
    found.sort(key=lambda s: s["distance_m"])
    return found[:limit]


def get_bike_status(place: str, need: str = "bike") -> dict:
    """查某個地點附近的 YouBike 站還有沒有車（或還有沒有空位）。

    適用時機：使用者想騎 YouBike 上課，需要知道附近哪一站借得到車；
    或快到目的地了，想知道哪一站還停得進去。

    Args:
        place: 地點名稱，例如 "成大圖書館"、"B501 資訊工程系館"。
        need: "bike" 表示要借車（看可借車輛數），"dock" 表示要還車（看空位數）。

    Returns:
        dict，包含：
        - status: "ok"、"not_found"（附近沒有符合條件的站）或 "error"
        - stations: 附近站點清單，依距離排序，每筆含 name、bikes、docks、
          distance_m、walk_minutes
        - place_name: 實際用來定位的地點名稱
    """
    if need not in ("bike", "dock"):
        return {"status": "error", "stations": [],
                "error_message": f"need 只能是 'bike' 或 'dock'，收到 {need!r}"}

    settings = load_settings()
    tz = settings.timezone
    found = resolve_place(place)
    if found["status"] != "ok":
        return {"status": "error", "stations": [], "place_name": place,
                "error_message": f"查不到「{place}」的座標，無法找附近的 YouBike 站"}

    try:
        stations = fetch_stations()
    except requests.Timeout:
        return {"status": "error", "stations": [], "error_message": "YouBike 查詢逾時"}
    except requests.RequestException as exc:
        return {"status": "error", "stations": [],
                "error_message": f"無法連線 YouBike（{type(exc).__name__}）"}
    except (YouBikeError, ValueError) as exc:
        return {"status": "error", "stations": [], "error_message": str(exc)}

    nearby = nearby_stations(stations, found["lat"], found["lon"], need)
    return {
        "status": "ok" if nearby else "not_found",
        "place_name": found["name"],
        "need": need,
        "stations": nearby,
        "fetched_at": datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds"),
        "note": ("附近沒有借得到車的站" if need == "bike" else "附近沒有還得了車的站")
                if not nearby else "",
    }
