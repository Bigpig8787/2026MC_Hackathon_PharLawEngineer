"""Tool 層：成大 GeoServer 的樓層平面圖（WMS 圖片 + WFS 房間輪廓）。

成大地圖網站（nckumap.ncku.edu.tw/map.php）的「平面圖圖層」不是截圖，是
GeoServer 的 WMS 圖層，命名規則 gis_room:<大樓代碼>_<樓層>，例如
gis_room:B029_2F。這件事寫在該站的 gips.map.gisMapWrapper.js 裡的
setFloorPlanVisibility()，GeoServer 位址在 gips.map.gisMapConfig.js 的
geoServerUrl。兩個端點都不需要金鑰或登入。

因此不需要爬網頁、也不需要人工截圖：

- WMS GetMap 直接回一張任意大小的 PNG，可透明，貼到頁面上就是平面圖；
- WFS GetFeature 回每個房間的多邊形與屬性（ClassNum 就是教室代碼），
  拿來把目標教室在圖上框出來。
- 哪一棟有哪幾層，離線查 data/ncku_floor_layers.json（由 GetCapabilities
  產生，見 scripts/build_floor_layers.py），不必每次下載 1.6MB 的 XML。

座標一律用 EPSG:3826（TWD97 二度分帶）：圖層範圍與 WFS 幾何都是這一套，
不混用就不必投影，算像素位置只是一次線性內插。
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = PROJECT_ROOT / "data" / "ncku_floor_layers.json"

GEOSERVER = "https://db.nckumap.ncku.edu.tw/geoNckuGis"
WORKSPACE = "gis_room"
SRS = "EPSG:3826"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

# 圖層範圍貼著建物邊緣，直接照它要圖會把牆切掉，留一點邊
BBOX_PADDING_RATIO = 0.04

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 700
MAX_PIXELS = 2048

_index_cache: dict | None = None


def load_index() -> dict:
    """讀樓層圖層索引。檔案不在時回空表，讓呼叫端照常走靜態備援。"""
    global _index_cache
    if _index_cache is None:
        if INDEX_PATH.is_file():
            _index_cache = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        else:
            _index_cache = {"buildings": {}}
    return _index_cache


def normalize_floor(floor: str) -> str:
    """把樓層寫法統一成圖層命名用的那一種（2f → 2F、夾層 → MEZ）。"""
    text = (floor or "").strip().upper()
    return text.replace("夾層", "MEZ").replace("違建", "ILLEGAL")


def list_floors(build_id: str) -> list[str]:
    """這棟大樓有平面圖的樓層，由低到高排。沒有就回空清單。"""
    floors = load_index()["buildings"].get((build_id or "").strip().upper(), {})

    def order(name: str) -> tuple:
        if name.startswith("B") and name[1:].rstrip("F").isdigit():
            return (0, -int(name[1:].rstrip("F")))
        digits = name.rstrip("F")
        return (1, int(digits)) if digits.isdigit() else (2, 0)

    return sorted(floors, key=order)


def _padded_bbox(box: list[float]) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = box
    px = (maxx - minx) * BBOX_PADDING_RATIO
    py = (maxy - miny) * BBOX_PADDING_RATIO
    return minx - px, miny - py, maxx + px, maxy + py


def floor_plan_url(build_id: str, floor: str, width: int = DEFAULT_WIDTH,
                   height: int = DEFAULT_HEIGHT, transparent: bool = True) -> dict:
    """組出某一棟某一層平面圖的 WMS 圖片網址。

    適用時機：要在畫面上顯示教室平面圖時使用。回傳的網址可以直接放進
    <img src>，不需要金鑰，也不必先把圖存到本地。

    Args:
        build_id: 成大 GIS 的大樓代碼，例如 "B029"（lookup_room 的 building_id）。
        floor: 樓層，例如 "2F"、"B1"。
        width、height: 要幾乘幾的圖片，單邊上限 2048。
        transparent: 是否去背。去背才能疊在底圖上。

    Returns:
        dict，包含：
        - status: "ok" 或 "not_found"（這一層沒有平面圖）
        - url: 可直接顯示的 PNG 網址
        - layer: GeoServer 的圖層名稱
        - bbox: 這張圖涵蓋的範圍（EPSG:3826，minx/miny/maxx/maxy）
        - width、height: 圖片尺寸，供換算教室在圖上的位置
        - floors: 這棟大樓還有哪些樓層有平面圖
    """
    bid = (build_id or "").strip().upper()
    fl = normalize_floor(floor)
    floors = list_floors(bid)
    result = {"status": "not_found", "build_id": bid, "floor": fl,
              "layer": f"{WORKSPACE}:{bid}_{fl}", "url": None, "bbox": None,
              "width": None, "height": None, "floors": floors}

    box = load_index()["buildings"].get(bid, {}).get(fl)
    if box is None:
        result["error_message"] = (
            f"成大 GeoServer 沒有 {bid} {fl} 的平面圖圖層"
            + (f"（這棟只有 {'、'.join(floors)}）" if floors else "（這棟沒有任何平面圖）"))
        return result

    w = max(1, min(int(width), MAX_PIXELS))
    h = max(1, min(int(height), MAX_PIXELS))
    minx, miny, maxx, maxy = _padded_bbox(box)
    query = urlencode({
        "service": "WMS", "version": "1.1.1", "request": "GetMap",
        "layers": result["layer"], "srs": SRS,
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "width": w, "height": h, "format": "image/png",
        "transparent": "true" if transparent else "false",
    })
    return {**result, "status": "ok", "url": f"{GEOSERVER}/wms?{query}",
            "bbox": {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
            "width": w, "height": h}


def get_rooms_on_floor(build_id: str, floor: str) -> dict:
    """查某一層每個房間的範圍與屬性（教室代碼、用途、容納人數）。

    適用時機：要在平面圖上把某一間教室框出來，或想知道那一層有哪些教室時使用。

    Args:
        build_id: 大樓代碼，例如 "B029"。
        floor: 樓層，例如 "2F"。

    Returns:
        dict，含 status 與 rooms；每個房間有 room_code、room_name、type、
        capacity、using_unit 與 bounds（EPSG:3826 的外接矩形）。
    """
    bid = (build_id or "").strip().upper()
    fl = normalize_floor(floor)
    layer = f"{WORKSPACE}:{bid}_{fl}"
    result = {"status": "error", "build_id": bid, "floor": fl,
              "layer": layer, "rooms": []}

    try:
        resp = requests.get(f"{GEOSERVER}/wfs",
                            params={"service": "WFS", "version": "1.0.0",
                                    "request": "GetFeature", "typeName": layer,
                                    "outputFormat": "application/json"},
                            timeout=30, headers={"User-Agent": USER_AGENT})
    except requests.Timeout:
        return {**result, "error_message": "成大 GeoServer 查詢逾時"}
    except requests.RequestException as exc:
        return {**result, "error_message": f"無法連線成大 GeoServer（{type(exc).__name__}）"}

    if resp.status_code != 200:
        return {**result, "error_message": f"成大 GeoServer 回應 HTTP {resp.status_code}"}
    try:
        payload = resp.json()
    except ValueError:
        # 圖層不存在時 GeoServer 回的是 XML 錯誤訊息，不是 JSON
        return {**result, "status": "not_found",
                "error_message": f"沒有 {layer} 這個圖層"}

    rooms = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        bounds = _bounds_of(feature.get("geometry") or {})
        rooms.append({
            "room_code": props.get("ClassNum") or "",
            "room_name": props.get("RoomName") or "",
            "type": props.get("Type") or "",
            "capacity": props.get("Capacity") or "",
            "using_unit": props.get("UsingUnitName") or "",
            "area": props.get("AREA"),
            "bounds": bounds,
        })
    return {**result, "status": "ok", "rooms": rooms}


def _bounds_of(geometry: dict) -> dict | None:
    """多邊形的外接矩形。只要框得住就夠，不需要完整幾何。"""
    xs: list[float] = []
    ys: list[float] = []

    def walk(node) -> None:
        if (isinstance(node, (list, tuple)) and len(node) >= 2
                and all(isinstance(v, (int, float)) for v in node[:2])):
            xs.append(float(node[0]))
            ys.append(float(node[1]))
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(geometry.get("coordinates"))
    if not xs:
        return None
    return {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}


def locate_room_on_plan(bounds: dict, bbox: dict) -> dict | None:
    """把房間的座標換算成圖片上的百分比位置，讓前端可以畫框。

    純函式。y 軸要翻轉：地理座標往北變大，圖片座標往下變大。
    """
    if not bounds or not bbox:
        return None
    span_x = bbox["maxx"] - bbox["minx"]
    span_y = bbox["maxy"] - bbox["miny"]
    if span_x <= 0 or span_y <= 0:
        return None
    left = (bounds["minx"] - bbox["minx"]) / span_x
    right = (bounds["maxx"] - bbox["minx"]) / span_x
    top = (bbox["maxy"] - bounds["maxy"]) / span_y
    bottom = (bbox["maxy"] - bounds["miny"]) / span_y
    return {"left": round(left * 100, 3), "top": round(top * 100, 3),
            "width": round((right - left) * 100, 3),
            "height": round((bottom - top) * 100, 3)}
