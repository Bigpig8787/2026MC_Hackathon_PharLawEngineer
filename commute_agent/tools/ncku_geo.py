"""Tool 層：查成大大樓的經緯度，以及純數學的距離與時間估算。

成大 GIS 的 buildinfo.htm?action=getCentroidByBuildId 會回傳大樓中心點座標
（2026-09-19 實測確認，walking_link.py 早期註解說「不含經緯度」是查錯端點）。
有了座標才能替停車場排「最近」的順序。

時間一律是估算值：直線距離乘上繞路係數再除以平均速度，不含紅綠燈與真實路網。
要精確時間得改接 Google Maps Routes API，那需要金鑰與計費。
"""

from __future__ import annotations

import math
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from api import load_settings

BUILDINFO_PATH = "/buildinfo.htm"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

EARTH_RADIUS_M = 6371008.8

# 直線距離換算實際路程的粗略係數：校園道路不是直的，實測上大約多三成
DETOUR_FACTOR = 1.3

# 公尺／分鐘。步行與單車取一般成人速度，汽機車取市區含停等的平均值。
SPEED_M_PER_MIN = {
    "walking": 80.0,
    "bicycling": 250.0,
    "driving": 400.0,
}
# 大眾運輸受班次影響太大，估了只會誤導，一律不給估算值
MODES_WITHOUT_ESTIMATE = ("transit",)
TRAVEL_MODES = ("walking", "bicycling", "driving", "transit")


class SchemaError(ValueError):
    """GIS 回應格式與預期不符。"""


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """兩點間的大圓距離（公尺）。純函式。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def estimate_minutes(straight_line_meters: float, travel_mode: str) -> int | None:
    """由直線距離估算行進分鐘數；大眾運輸回 None 表示無法估算。"""
    if travel_mode in MODES_WITHOUT_ESTIMATE:
        return None
    speed = SPEED_M_PER_MIN.get(travel_mode)
    if speed is None:
        raise ValueError(f"不支援的交通模式 {travel_mode!r}，可用：{TRAVEL_MODES}")
    return max(1, round(straight_line_meters * DETOUR_FACTOR / speed))


def strip_build_code(name: str) -> str:
    """去掉大樓名稱前面的代碼，"B208 理學教學大樓" → "理學教學大樓"。"""
    parts = (name or "").split(" ", 1)
    return parts[1] if len(parts) == 2 and parts[0][:1].isalpha() else (name or "")


def best_match(rows: list[dict], query: str) -> dict | None:
    """從模糊搜尋結果挑最像的一筆。

    GIS 主要靠 keyword 欄位的別名比對：「奇美樓」的正式名稱其實是
    「D501 奇美大樓」，只有 keyword 對得上。但它也會撈進不相干的結果——
    查「理學」第一筆是「管理學院綜合大樓」（名稱裡剛好有「理學」兩字），
    正確答案「B208 理學教學大樓」排第二。

    因此先看別名、再看名稱，都沒有才退回 GIS 自己的排序。
    """
    if not rows:
        return None
    q = (query or "").strip()
    if not q:
        return rows[0]

    def score(row: dict) -> int:
        if q in (row.get("keyword") or ""):
            return 2
        if q in strip_build_code(row.get("name", "")):
            return 1
        return 0

    # 同分時保留 GIS 原本的相關性排序，所以用負的索引當次要鍵
    return max(enumerate(rows), key=lambda pair: (score(pair[1]), -pair[0]))[1]


# GIS 索引裡的名稱不含校名，使用者卻常寫「成大圖書館」，查詢前要先剝掉
NCKU_PREFIXES = ("國立成功大學", "成功大學", "成大")


def place_candidates(query: str) -> list[str]:
    """回傳查 GIS 時要依序嘗試的關鍵字：原字串，以及剝掉校名前綴後的字串。"""
    q = (query or "").strip()
    candidates = [q] if q else []
    for prefix in NCKU_PREFIXES:
        if q.startswith(prefix) and len(q) > len(prefix):
            trimmed = q[len(prefix):].strip()
            if trimmed and trimmed not in candidates:
                candidates.append(trimmed)
    return candidates


def _get(endpoint: str, params: dict, timeout: float) -> dict:
    resp = requests.get(endpoint, params=params, timeout=timeout,
                        headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        raise SchemaError(f"GIS 回應 HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SchemaError("GIS 回應不是 JSON") from exc


def _now_iso(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds")


def get_building_location(query: str) -> dict:
    """查成大某棟大樓的中心點經緯度。

    適用時機：需要知道大樓實際位置以便計算距離時使用；只是要給使用者
    導航連結的話用 build_route_link 就夠了，不必先查座標。

    Args:
        query: 大樓名稱或關鍵字，例如 "資訊系館"、"B501"、"奇美樓"。

    Returns:
        dict，包含：
        - status: "ok"、"not_found" 或 "error"
        - build_id、name: 大樓代碼與 GIS 上的正式名稱
        - lat、lon: 中心點緯度與經度；查不到時為 None
        - campus_id: GIS 的校區代碼。注意這與停車系統的校區代碼不是同一套，
          不可互相套用
    """
    settings = load_settings()
    tz = settings.timezone
    endpoint = settings.ncku_gis_base_url.rstrip("/") + BUILDINFO_PATH
    q = (query or "").strip()
    result = {"status": "ok", "query": q, "build_id": "", "name": "",
              "lat": None, "lon": None, "campus_id": "", "fetched_at": _now_iso(tz)}

    if not q:
        return {**result, "status": "error", "error_message": "查詢字串不可為空"}

    try:
        found = _get(endpoint, {"action": "search", "q": q, "locale": "zh-tw"},
                     settings.http_timeout_seconds)
        row = best_match(found.get("data") or [], q)
        if row is None:
            return {**result, "status": "not_found"}
        result.update(build_id=row.get("id", ""), name=row.get("name", ""),
                      campus_id=row.get("campusId", ""))

        centroid = _get(endpoint, {"action": "getCentroidByBuildId",
                                   "buildId": result["build_id"], "locale": "zh-tw"},
                        settings.http_timeout_seconds)
        points = centroid.get("data") or []
        if not points:
            return {**result, "status": "not_found"}
        result["lat"] = float(points[0]["lat"])
        result["lon"] = float(points[0]["lon"])
    except requests.Timeout:
        return {**result, "status": "error", "error_message": "成大地理資訊系統查詢逾時"}
    except requests.RequestException as exc:
        return {**result, "status": "error",
                "error_message": f"無法連線成大地理資訊系統（{type(exc).__name__}）"}
    except (SchemaError, KeyError, TypeError, ValueError) as exc:
        return {**result, "status": "error", "error_message": f"回應格式異常：{exc}"}

    result["source"] = f"{endpoint}?{urlencode({'action': 'getCentroidByBuildId', 'buildId': result['build_id']})}"
    return result


def resolve_place(query: str) -> dict:
    """查一個成大校內地點的座標，會自動剝掉「成大」這類校名前綴。

    查不到時回傳 status="not_found"，代表這個地點不在成大 GIS 的索引裡
    （例如校外地址或火車站）。呼叫端應如實告知使用者無法估算距離，
    不要改用任何猜測的座標。
    """
    for candidate in place_candidates(query):
        result = get_building_location(candidate)
        if result["status"] == "ok":
            result["matched_query"] = candidate
            return result
        if result["status"] == "error":
            return result
    return {"status": "not_found", "query": query, "build_id": "", "name": "",
            "lat": None, "lon": None, "campus_id": ""}
