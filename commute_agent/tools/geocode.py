"""Tool 層：把地點名稱或地址轉成座標。

成大 GIS 只認得校內大樓，使用者的住家地址查不到，導致「附近的 YouBike 站」
與「附近的公車站」在校外出發時整個失效。這裡補上 Google Geocoding 當後援：

1. 先查成大 GIS（免費，校內地點最準，回傳的還是正式大樓名稱）。
2. GIS 查不到才呼叫 Google（會計費，但一個地址只會查一次）。

地址不會移動，所以查到的座標永久快取在記憶體裡，重複查詢不再花錢。
"""

from __future__ import annotations

import requests

from api import load_settings
from commute_agent.tools.ncku_geo import resolve_place

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

# 限制在台灣，避免同名地址被解析到國外
REGION = "tw"
LANGUAGE = "zh-TW"

_cache: dict[str, dict] = {}


def parse_geocode(payload: dict) -> dict | None:
    """從 Google Geocoding 回應取出第一筆座標；查無結果時回 None。"""
    if not isinstance(payload, dict) or payload.get("status") != "OK":
        return None
    results = payload.get("results") or []
    if not results:
        return None
    location = results[0].get("geometry", {}).get("location", {})
    if "lat" not in location or "lng" not in location:
        return None
    return {"lat": float(location["lat"]), "lon": float(location["lng"]),
            "name": results[0].get("formatted_address", "")}


def _by_google(place: str) -> dict:
    settings = load_settings()
    if not settings.google_maps_api_key:
        return {"status": "not_found", "lat": None, "lon": None, "name": "",
                "source": "google", "error_message": "未設定 GOOGLE_MAPS_API_KEY"}
    try:
        resp = requests.get(
            GEOCODE_URL,
            params={"address": place, "key": settings.google_maps_api_key,
                    "region": REGION, "language": LANGUAGE},
            timeout=max(settings.http_timeout_seconds, 15),
            headers={"User-Agent": USER_AGENT})
    except requests.Timeout:
        return {"status": "error", "lat": None, "lon": None, "name": "",
                "source": "google", "error_message": "Google Geocoding 逾時"}
    except requests.RequestException as exc:
        return {"status": "error", "lat": None, "lon": None, "name": "",
                "source": "google",
                "error_message": f"無法連線 Google Geocoding（{type(exc).__name__}）"}

    if resp.status_code != 200:
        return {"status": "error", "lat": None, "lon": None, "name": "",
                "source": "google",
                "error_message": f"Google Geocoding 回應 HTTP {resp.status_code}"}

    try:
        found = parse_geocode(resp.json())
    except ValueError:
        return {"status": "error", "lat": None, "lon": None, "name": "",
                "source": "google", "error_message": "Google Geocoding 回應不是 JSON"}

    if not found:
        return {"status": "not_found", "lat": None, "lon": None, "name": "",
                "source": "google"}
    return {"status": "ok", "source": "google", **found}


def geocode_place(place: str) -> dict:
    """查一個地點的座標，校內走成大 GIS，校外才用 Google。

    Args:
        place: 地點名稱或地址，例如 "成大圖書館" 或 "台南市東區某路一段1號"。

    Returns:
        dict，含 status（"ok"／"not_found"／"error"）、lat、lon、name
        與 source（"ncku_gis" 或 "google"，讓呼叫端知道花了錢沒有）。
    """
    key = (place or "").strip()
    if not key:
        return {"status": "error", "lat": None, "lon": None, "name": "",
                "source": "", "error_message": "地點不可為空"}
    if key in _cache:
        return _cache[key]

    found = resolve_place(key)
    if found["status"] == "ok":
        result = {"status": "ok", "lat": found["lat"], "lon": found["lon"],
                  "name": found["name"], "source": "ncku_gis"}
    else:
        result = _by_google(key)

    # 只快取成功的結果：查不到可能是暫時的網路問題，不該永久記住失敗
    if result["status"] == "ok":
        _cache[key] = result
    return result
