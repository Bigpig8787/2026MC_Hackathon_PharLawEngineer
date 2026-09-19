"""Tool 層：查 TDX 路況事件（車禍、施工、封閉），看起點或目的地周邊是否有異常。

端點與驗證：
- 資料端點：GET {TDX_BASE_URL}/api/basic/v1/Traffic/RoadEvent/LiveEvent/City/{City}
  （使用者於 2026-09-19 提供，實測確認未帶授權會回 401 "Valid API Key Required"）。
- TDX 全平台共用 OAuth2 client_credentials 驗證，端點固定為 TOKEN_URL，
  這支對 Bus、YouBike 等其他 TDX 資料集也適用，非本檔專屬。

**已知限制（2026-09-19，尚未取得 TDX_CLIENT_ID/SECRET，無法對真實端點試打)**：
parse_road_events() 對回應欄位採「多種可能命名都嘗試比對」的寬鬆解析，
命中的候選命名來自 TDX 其他資料集（如站牌座標 Position.PositionLon/PositionLat）
的通用慣例，但 RoadEvent 資料集本身的實際欄位命名尚未經真實回應驗證。
一旦拿到金鑰，請先跑 scripts/smoke_tdx_road_events.py，若解析失敗，
SchemaError 訊息會列出實際欄位名稱，照那個修 parse_road_events 即可。
事件的分類代碼（EventType/SubEventType 等數字碼）目前沒有找到官方對照表，
因此本檔不將代碼轉譯成中文說法，只在有現成 Description 文字時原樣帶出，
避免顯示看起來確定、實際上是猜的分類。
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from api import load_settings
from commute_agent.tools.ncku_geo import haversine_meters

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
TDX_BASE_URL = "https://tdx.transportdata.tw"
ROAD_EVENT_PATH = "/api/basic/v1/Traffic/RoadEvent/LiveEvent/City/{city}"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

# 換到的 token 提前這麼多秒視為過期，避免卡在「剛好過期」那一刻送出請求
TOKEN_SAFETY_MARGIN_S = 60.0
DEFAULT_RADIUS_M = 500.0

# client_id -> (access_token, 過期時間的 epoch 秒數)。TDX token 效期通常以天計，
# 快取起來才不會每次查路況都重新驗證一次。
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


class SchemaError(ValueError):
    """TDX 回應格式與預期不符（可能是欄位命名與本檔假設的不同，或對方改版）。"""


class TokenError(RuntimeError):
    """換 TDX access token 失敗。"""


def _now_iso(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds")


def reset_token_cache() -> None:
    """清空 token 快取。測試或金鑰更換後使用。"""
    _TOKEN_CACHE.clear()


def _fetch_access_token(client_id: str, client_secret: str, timeout: float) -> tuple[str, float]:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    if resp.status_code != 200:
        raise TokenError(f"TDX 驗證伺服器回應 HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise TokenError("TDX 驗證伺服器回應不是 JSON") from exc
    token = body.get("access_token")
    if not token:
        raise TokenError("TDX 驗證回應沒有 access_token 欄位")
    expires_in = float(body.get("expires_in") or 3600)
    return token, expires_in


def get_access_token(client_id: str, client_secret: str, timeout: float, now: float | None = None) -> str:
    """回傳可用的 TDX access token，效期內重複呼叫不會再打驗證端點。

    Args:
        now: 目前時間的 epoch 秒數，用於判斷快取是否過期；預設 `time.time()`。
            測試以外通常不需要傳。

    Raises:
        TokenError: 驗證失敗（金鑰錯誤、逾時、格式異常）。
    """
    now = time.time() if now is None else now
    cached = _TOKEN_CACHE.get(client_id)
    if cached is not None and cached[1] > now:
        return cached[0]
    try:
        token, expires_in = _fetch_access_token(client_id, client_secret, timeout)
    except requests.Timeout as exc:
        raise TokenError("TDX 驗證逾時") from exc
    except requests.RequestException as exc:
        raise TokenError(f"無法連線 TDX 驗證伺服器（{type(exc).__name__}）") from exc
    _TOKEN_CACHE[client_id] = (token, now + expires_in - TOKEN_SAFETY_MARGIN_S)
    return token


def _first_present(row: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


# 各欄位嘗試比對的候選命名，由最可能到最寬鬆。Position 巢狀寫法沿用 TDX
# 站牌類資料集（Bus/YouBike）常見的 Position.PositionLon/PositionLat 慣例；
# 其餘是常見的替代拼法。真實回應若都對不上，SchemaError 會印出實際欄位名。
_ID_KEYS = ("EventID", "RoadEventID", "ID", "Id")
_DESCRIPTION_KEYS = ("Description", "EventDescription", "Comment", "Remark")
_TYPE_KEYS = ("SubEventType", "EventType", "EventCategory")
_ROAD_NAME_KEYS = ("RoadName", "RoadSection", "Location", "RoadID")
_TIME_KEYS = ("ReportStartTime", "StartTime", "PublishTime", "SrcUpdateTime", "UpdateTime")
_FLAT_LON_KEYS = ("PositionLon", "Longitude", "Lon", "lon", "longitude")
_FLAT_LAT_KEYS = ("PositionLat", "Latitude", "Lat", "lat", "latitude")


def _extract_position(row: dict) -> tuple[float, float] | None:
    position = row.get("Position")
    if isinstance(position, dict):
        lon = _first_present(position, _FLAT_LON_KEYS)
        lat = _first_present(position, _FLAT_LAT_KEYS)
        if lon is not None and lat is not None:
            return float(lon), float(lat)
    lon = _first_present(row, _FLAT_LON_KEYS)
    lat = _first_present(row, _FLAT_LAT_KEYS)
    if lon is not None and lat is not None:
        return float(lon), float(lat)
    return None


def parse_road_events(raw) -> list[dict]:
    """把 TDX RoadEvent LiveEvent 的原始回應轉成統一格式的事件清單。

    寬鬆比對多種可能的欄位命名（見檔案開頭說明）；一筆事件裡完全找不到
    可用座標就整批視為格式不符，丟出 SchemaError 並附上實際看到的欄位名，
    而不是悄悄漏掉或猜一個座標。
    """
    if isinstance(raw, dict):
        rows = raw.get("RoadEvents") or raw.get("Events") or raw.get("Data") or raw.get("data")
        if rows is None:
            raise SchemaError(f"回應是物件但找不到事件陣列，實際欄位：{sorted(raw.keys())}")
    else:
        rows = raw
    if not isinstance(rows, list):
        raise SchemaError(f"回應不是陣列也不是可辨識的物件包裝，型別：{type(raw).__name__}")
    if not rows:
        return []

    events = []
    for row in rows:
        if not isinstance(row, dict):
            raise SchemaError(f"事件不是物件，型別：{type(row).__name__}")
        position = _extract_position(row)
        if position is None:
            raise SchemaError(
                f"找不到座標欄位，實際欄位：{sorted(row.keys())}（本檔預期 Position.PositionLon/"
                "PositionLat 或同義的扁平欄位，請對照這份 keys 更新 parse_road_events）"
            )
        lon, lat = position
        type_code = _first_present(row, _TYPE_KEYS)
        events.append({
            "event_id": _first_present(row, _ID_KEYS) or "",
            "description": _first_present(row, _DESCRIPTION_KEYS) or "",
            "type_code": type_code,
            # 目前沒有官方代碼對照表，不把數字碼轉譯成中文分類，避免顯示錯誤資訊
            "type_is_code": type_code is not None and _first_present(row, _DESCRIPTION_KEYS) is None,
            "road_name": _first_present(row, _ROAD_NAME_KEYS) or "",
            "reported_at": _first_present(row, _TIME_KEYS),
            "lat": lat,
            "lon": lon,
            "raw": row,
        })
    return events


def _result(status: str, mode: str, source: str, tz: str,
            events: list[dict] | None = None, error_message: str | None = None) -> dict:
    result = {
        "status": status,
        "events": events or [],
        "count": len(events or []),
        "mode": mode,
        "source": source,
        "fetched_at": _now_iso(tz),
    }
    if error_message:
        result["error_message"] = error_message
    return result


def get_road_events(city: str, lat: float, lon: float, radius_m: float = DEFAULT_RADIUS_M) -> dict:
    """查某座標周邊 radius_m 公尺內，目前是否有車禍、施工或封閉等路況事件（TDX 即時路況）。

    適用時機：要提醒使用者出發點或目的地附近的路況異常時使用，
    通常會對起點與目的地座標各呼叫一次。

    Args:
        city: TDX 的城市代碼，成大所在的台南為 "Tainan"。
        lat: 查詢中心緯度。
        lon: 查詢中心經度。
        radius_m: 篩選半徑（公尺），預設 500。

    Returns:
        dict，包含：
        - status: "ok" 或 "error"
        - events: 半徑內的事件清單，依距離近到遠排序，每筆含 event_id、
          description、type_code、type_is_code（分類是否只有數字代碼、
          沒有文字說明）、road_name、reported_at、lat、lon、distance_m
        - count: events 的筆數
        - source、fetched_at、mode: 資料來源網址、查詢時間、live 或 fixture 模式
        - error_message: 僅在 status 為 "error" 時出現

    注意：分類代碼（type_code）目前沒有官方中文對照表，type_is_code 為
    True 時代表只有數字代碼可用，轉述給使用者時不要編一個分類名稱。
    """
    settings = load_settings()
    mode, tz = settings.provider_mode, settings.timezone
    endpoint = TDX_BASE_URL + ROAD_EVENT_PATH.format(city=city)
    source = f"{endpoint} (radius={radius_m:g}m)"

    if mode == "fixture":
        from pathlib import Path
        import json

        path = Path(__file__).resolve().parent.parent / "fixtures" / "ncku_traffic" / f"{city}.json"
        if not path.is_file():
            return _result("error", mode, source, tz,
                           error_message=f"fixture 模式下沒有 {city!r} 的路況錄製資料")
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            token = get_access_token(settings.tdx_client_id, settings.tdx_client_secret,
                                     settings.http_timeout_seconds)
        except TokenError as exc:
            return _result("error", mode, source, tz, error_message=str(exc))

        try:
            resp = requests.get(
                endpoint,
                params={"$format": "JSON"},
                timeout=settings.http_timeout_seconds,
                headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"},
            )
        except requests.Timeout:
            return _result("error", mode, source, tz, error_message="TDX 路況事件查詢逾時")
        except requests.RequestException as exc:
            return _result("error", mode, source, tz,
                           error_message=f"無法連線 TDX 路況事件服務（{type(exc).__name__}）")
        if resp.status_code == 401:
            return _result("error", mode, source, tz, error_message="TDX 金鑰無效或已過期")
        if resp.status_code != 200:
            return _result("error", mode, source, tz,
                           error_message=f"TDX 路況事件服務回應 HTTP {resp.status_code}")
        try:
            raw = resp.json()
        except ValueError:
            return _result("error", mode, source, tz, error_message="TDX 路況事件服務回應不是 JSON")

    try:
        events = parse_road_events(raw)
    except SchemaError as exc:
        return _result("error", mode, source, tz, error_message=f"回應格式異常：{exc}")

    nearby = []
    for event in events:
        distance = haversine_meters(lat, lon, event["lat"], event["lon"])
        if distance <= radius_m:
            nearby.append({**event, "distance_m": round(distance)})
    nearby.sort(key=lambda e: e["distance_m"])

    return _result("ok", mode, source, tz, events=nearby)
