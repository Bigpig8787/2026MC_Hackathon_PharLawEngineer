"""Tool 層：查詢成大教室所在的大樓與樓層（成大地理資訊系統 nckumap）。

Tool 只負責「打 API、整理格式」，不做任何決策，也不呼叫其他 Tool 或 Skill。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from api import load_settings

ROOMINFO_PATH = "/roominfo.htm"
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "ncku_gis" / "roominfo"
MAX_QUERY_LENGTH = 50
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"


class SchemaError(ValueError):
    """nckumap 回應格式與預期不符（可能是對方改版）。"""


def _normalize(text: str) -> str:
    return (text or "").strip().casefold()


def parse_room_response(payload: dict, query: str) -> list[dict]:
    """把 nckumap roominfo 的原始回應轉成統一格式的候選清單。"""
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SchemaError("回應缺少 data 陣列")

    q = _normalize(query)
    candidates = []
    for row in rows:
        room_code = row.get("classNum") or ""
        room_name = row.get("name") or ""
        candidates.append({
            "room_code": room_code,
            "room_name": room_name,
            "floor": row.get("floor") or "",
            "space_id": row.get("id") or "",
            "building_id": row.get("buildId") or "",
            "building_name": row.get("buildName") or "",
            "building_name_en": row.get("buildNameEn") or "",
            "exact_match": q in (_normalize(room_code), _normalize(room_name)),
        })
    return candidates


def _now_iso(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds")


def _result(status: str, query: str, mode: str, source: str, tz: str,
            candidates: list | None = None, error_message: str | None = None) -> dict:
    candidates = candidates or []
    result = {
        "status": status,
        "query": query,
        "candidates": candidates,
        "exact_match_count": sum(1 for c in candidates if c["exact_match"]),
        "mode": mode,
        "source": source,
        "fetched_at": _now_iso(tz),
    }
    if error_message:
        result["error_message"] = error_message
    return result


def lookup_room(query: str) -> dict:
    """查詢成功大學教室位於哪一棟大樓、哪一層樓。

    適用時機：已知課表上的教室代碼（例如 "4264"、"65304"）或教室名稱
    （例如 "格致廳"、"繁城講堂"），需要知道它實際在哪棟大樓、幾樓時使用。

    注意：課表上寫的大樓名稱可能與實際不同（例如同為「資訊系館」，
    4264 在 B501 舊館、65304 在 B502 新館），應以本工具回傳的 building_name 為準。

    Args:
        query: 教室代碼或教室名稱，例如 "4264" 或 "格致廳"。

    Returns:
        dict，包含：
        - status: "ok"（找到）、"not_found"（查無結果）或 "error"（查詢失敗）
        - candidates: 候選教室清單，每筆含 room_code、room_name、floor、
          building_id、building_name、exact_match（是否與查詢完全相符）
        - exact_match_count: 完全相符的筆數；為 0 時代表只有模糊結果，需再確認
        - source、fetched_at、mode: 資料來源網址、查詢時間、live 或 fixture 模式
        - error_message: 僅在 status 為 "error" 時出現
    """
    settings = load_settings()
    mode, tz = settings.provider_mode, settings.timezone
    endpoint = settings.ncku_gis_base_url.rstrip("/") + ROOMINFO_PATH
    q = (query or "").strip()
    params = {"action": "search", "locale": "zh-tw", "q": q,
              "exactlyMatch": "false", "start": "0", "page": "1", "limit": "20"}
    source = f"{endpoint}?{urlencode(params)}"

    if not q or len(q) > MAX_QUERY_LENGTH:
        return _result("error", q, mode, source, tz,
                       error_message=f"查詢字串必須為 1 到 {MAX_QUERY_LENGTH} 個字元")

    if mode == "fixture":
        path = FIXTURE_DIR / f"{q}.json"
        if not path.is_file():
            return _result("error", q, mode, source, tz,
                           error_message=f"fixture 模式下沒有 {q!r} 的錄製資料")
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            resp = requests.get(endpoint, params=params, timeout=settings.http_timeout_seconds,
                                headers={"User-Agent": USER_AGENT})
        except requests.Timeout:
            return _result("error", q, mode, source, tz, error_message="成大地理資訊系統查詢逾時")
        except requests.RequestException as exc:
            return _result("error", q, mode, source, tz,
                           error_message=f"無法連線成大地理資訊系統（{type(exc).__name__}）")
        if resp.status_code != 200:
            return _result("error", q, mode, source, tz,
                           error_message=f"成大地理資訊系統回應 HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError:
            return _result("error", q, mode, source, tz, error_message="成大地理資訊系統回應不是 JSON")

    try:
        candidates = parse_room_response(payload, q)
    except SchemaError as exc:
        return _result("error", q, mode, source, tz, error_message=f"回應格式異常：{exc}")

    status = "ok" if candidates else "not_found"
    return _result(status, q, mode, source, tz, candidates=candidates)
