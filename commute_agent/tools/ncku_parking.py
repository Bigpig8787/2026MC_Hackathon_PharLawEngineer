"""Tool 層：查詢成大校園管制停車場即時剩餘車位（apss.oga.ncku.edu.tw）。

這支 API 回傳的是現成的 HTML 片段（網站直接塞進頁面顯示），不是 JSON，
所以本檔用 BeautifulSoup 解析標籤，而不是像 ncku_room.py 那樣解析 JSON 欄位。
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from api import load_settings

READ_PATH = "/read"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

# 使用者於 2026-09-19 逐一切換 apss.oga.ncku.edu.tw 的校區下拉選單，
# 並比對 DevTools 中 Payload 的 campus 值後確認。
CAMPUS_CODES = {
    "光復": "A", "成功": "B", "自強": "C", "成杏": "D",
    "力行": "E", "敬業": "F", "勝利": "G",
}
VEHICLE_TABS = {"機車": "moto", "汽車": "car"}

NO_DATA_MARKER = "查無符合條件之停車場資料"


class SchemaError(ValueError):
    """回應的 HTML 結構與預期不符（可能是對方改版）。"""


def parse_parking_html(html: str) -> list[dict]:
    """把停車頁 read 端點回傳的 HTML 片段轉成統一格式的停車場清單。"""
    if not html or not html.strip():
        raise SchemaError("回應內容為空")

    if NO_DATA_MARKER in html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select(".park-data")
    if not blocks:
        raise SchemaError("找不到 .park-data 區塊，且非「查無資料」訊息，頁面結構可能已變更")

    lots = []
    for block in blocks:
        name_tag = block.select_one(".mb-2")
        campus_tag = block.select_one(".campus")
        number_tag = block.select_one(".number")
        if not (name_tag and campus_tag and number_tag):
            raise SchemaError("停車場區塊缺少必要欄位（名稱／校區／車位數）")
        digits = re.sub(r"\D", "", number_tag.get_text())
        if not digits:
            raise SchemaError(f"無法從 {number_tag.get_text()!r} 解析出車位數字")
        lots.append({
            "name": name_tag.get_text(strip=True),
            "campus": campus_tag.get_text(strip=True),
            "available": int(digits),
        })
    return lots


def _now_iso(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds")


def _result(status: str, mode: str, source: str, tz: str,
            lots: list | None = None, error_message: str | None = None) -> dict:
    result = {
        "status": status,
        "lots": sorted(lots, key=lambda l: l["available"], reverse=True) if lots else [],
        "mode": mode,
        "source": source,
        "fetched_at": _now_iso(tz),
    }
    if error_message:
        result["error_message"] = error_message
    return result


def get_parking_availability(campus: str, vehicle_type: str) -> dict:
    """查詢成大某校區、某種車輛的即時剩餘停車位。

    適用時機：使用者想知道某個校區目前哪個停車場還有位子，
    例如騎機車要停成杏校區，或開車要停自強校區時使用。

    注意：某些校區可能沒有該車種的停車場（例如勝利校區查機車會沒有資料），
    這種情況 status 仍為 "ok"，只是 lots 是空清單，不代表查詢失敗。

    Args:
        campus: 校區中文名稱，例如 "自強"、"光復"、"成功"、"成杏"、
            "力行"、"敬業"、"勝利"（可帶或不帶「校區」二字）。
        vehicle_type: "機車" 或 "汽車"。

    Returns:
        dict，包含：
        - status: "ok"（查詢成功，可能沒有停車場）或 "error"（查詢失敗）
        - lots: 停車場清單，依剩餘車位由多到少排序，每筆含 name、campus、available
        - source、fetched_at、mode: 資料來源網址、查詢時間、live 或 fixture 模式
        - error_message: 僅在 status 為 "error" 時出現
    """
    settings = load_settings()
    mode, tz = settings.provider_mode, settings.timezone

    campus_key = campus.strip().removesuffix("校區")
    if campus_key not in CAMPUS_CODES:
        raise ValueError(f"不支援的校區 {campus!r}，可用選項：{list(CAMPUS_CODES)}")
    if vehicle_type not in VEHICLE_TABS:
        raise ValueError(f"不支援的車種 {vehicle_type!r}，可用選項：{list(VEHICLE_TABS)}")

    code, tab = CAMPUS_CODES[campus_key], VEHICLE_TABS[vehicle_type]
    endpoint = settings.ncku_parking_base_url.rstrip("/") + READ_PATH
    source = f"{endpoint} (campus={code}, tab={tab})"

    if mode == "fixture":
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "fixtures" / "ncku_parking" / f"{code}_{tab}.html"
        if not path.is_file():
            return _result("error", mode, source, tz,
                           error_message=f"fixture 模式下沒有 {code}_{tab} 的錄製資料")
        html = path.read_text(encoding="utf-8")
    else:
        try:
            resp = requests.post(endpoint, data={"campus": code, "tab": tab},
                                 timeout=settings.http_timeout_seconds,
                                 headers={"User-Agent": USER_AGENT})
        except requests.Timeout:
            return _result("error", mode, source, tz, error_message="成大停車即時系統查詢逾時")
        except requests.RequestException as exc:
            return _result("error", mode, source, tz,
                           error_message=f"無法連線成大停車即時系統（{type(exc).__name__}）")
        if resp.status_code != 200:
            return _result("error", mode, source, tz,
                           error_message=f"成大停車即時系統回應 HTTP {resp.status_code}")
        html = resp.text

    try:
        lots = parse_parking_html(html)
    except SchemaError as exc:
        return _result("error", mode, source, tz, error_message=f"回應格式異常：{exc}")

    return _result("ok", mode, source, tz, lots=lots)
