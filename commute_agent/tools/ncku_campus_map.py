"""Tool 層：成大 GeoServer 的校區底圖，以及地圖與圖片座標的換算。

平面圖用的是 gis_room 那組圖層（見 ncku_floorplan.py），校區底圖則是
gis 工作區裡的幾個圖層疊起來：校區範圍、綠地、道路、建物、建物名稱。
那張「全校圖」就是這麼來的，不必截圖。

座標一律用 EPSG:4326。GeoServer 會自己投影，而用經緯度的好處是
Google Routes 回的路線點可以直接線性換算成圖片上的位置，中間不必再轉一次；
代價是經度在這個緯度上比緯度「短」，所以 bbox 要先依 cos(緯度) 校正長寬比，
否則畫出來的校園會被拉扁。
"""

from __future__ import annotations

import math
from urllib.parse import urlencode

import requests

GEOSERVER = "https://db.nckumap.ncku.edu.tw/geoNckuGis"
SRS = "EPSG:4326"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

# 由下往上疊：校區底色 → 綠地 → 道路 → 建物 → 建物名稱
BASE_LAYERS = ("gis:gis_campus", "gis:gis_greenspace", "gis:gis_roadline",
               "gis:gis_building", "gis:gis_building_name")
BUILDING_LAYER = "gis:gis_building"

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 760
MAX_PIXELS = 2048

# 路線貼著圖邊很難看，兩端各留這個比例的空白
BBOX_PADDING_RATIO = 0.18
# 起訖點很近時 bbox 會小到整張圖只剩兩棟樓，給一個最小跨距（約 110 公尺）
MIN_SPAN_DEGREES = 0.001


def bbox_for(points: list[tuple[float, float]], width: int = DEFAULT_WIDTH,
             height: int = DEFAULT_HEIGHT) -> dict | None:
    """算出涵蓋這些點、且長寬比與圖片相符的 bbox。

    純函式。points 是 (lat, lon) 清單。
    """
    if not points:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    minlat, maxlat = min(lats), max(lats)
    minlon, maxlon = min(lons), max(lons)

    span_lat = max(maxlat - minlat, MIN_SPAN_DEGREES)
    span_lon = max(maxlon - minlon, MIN_SPAN_DEGREES)
    span_lat *= 1 + BBOX_PADDING_RATIO * 2
    span_lon *= 1 + BBOX_PADDING_RATIO * 2

    clat = (minlat + maxlat) / 2
    clon = (minlon + maxlon) / 2

    # 一度經度在這個緯度上只有一度緯度的 cos(lat) 那麼長，先換算成等距再比長寬
    shrink = max(math.cos(math.radians(clat)), 1e-6)
    target = width / height
    if (span_lon * shrink) / span_lat < target:
        span_lon = target * span_lat / shrink
    else:
        span_lat = (span_lon * shrink) / target

    return {"minlon": clon - span_lon / 2, "minlat": clat - span_lat / 2,
            "maxlon": clon + span_lon / 2, "maxlat": clat + span_lat / 2}


def to_percent(lat: float, lon: float, bbox: dict) -> dict | None:
    """把經緯度換算成圖片上的百分比位置。

    純函式。y 要翻轉：緯度往北變大，圖片座標往下變大。
    """
    if not bbox:
        return None
    span_lon = bbox["maxlon"] - bbox["minlon"]
    span_lat = bbox["maxlat"] - bbox["minlat"]
    if span_lon <= 0 or span_lat <= 0:
        return None
    return {"left": round((lon - bbox["minlon"]) / span_lon * 100, 3),
            "top": round((bbox["maxlat"] - lat) / span_lat * 100, 3)}


def campus_map_url(bbox: dict, width: int = DEFAULT_WIDTH,
                   height: int = DEFAULT_HEIGHT, layers: tuple = BASE_LAYERS) -> dict:
    """組出校區底圖的 WMS 圖片網址。

    適用時機：要在畫面上顯示一張帶建物名稱的校園圖，並在上面標路線時使用。

    Args:
        bbox: 要涵蓋的範圍，含 minlon、minlat、maxlon、maxlat（EPSG:4326）。
        width、height: 圖片尺寸，單邊上限 2048。
        layers: 要疊哪些 GeoServer 圖層，由下往上。

    Returns:
        dict，含 status、url、bbox、width、height、layers。
    """
    result = {"status": "not_found", "url": None, "bbox": bbox,
              "width": None, "height": None, "layers": list(layers)}
    if not bbox:
        return {**result, "error_message": "沒有可以畫圖的範圍"}

    w = max(1, min(int(width), MAX_PIXELS))
    h = max(1, min(int(height), MAX_PIXELS))
    query = urlencode({
        "service": "WMS", "version": "1.1.1", "request": "GetMap",
        "layers": ",".join(layers), "srs": SRS,
        "bbox": f"{bbox['minlon']},{bbox['minlat']},{bbox['maxlon']},{bbox['maxlat']}",
        "width": w, "height": h, "format": "image/png", "transparent": "false",
    })
    return {**result, "status": "ok", "url": f"{GEOSERVER}/wms?{query}",
            "width": w, "height": h}


def buildings_in_bbox(bbox: dict, limit: int = 40) -> dict:
    """查這個範圍裡有哪些建物，供標示地標之用。

    適用時機：要講「經過某某大樓再右轉」這種指路方式時，先用這支拿到
    路線附近真的存在的建物名稱，才不會講出校園裡沒有的地標。

    Args:
        bbox: 範圍，含 minlon、minlat、maxlon、maxlat（EPSG:4326）。
        limit: 最多回幾棟。

    Returns:
        dict，含 status 與 buildings（每棟有 name 與 lat、lon 中心點）。
    """
    result = {"status": "error", "buildings": []}
    if not bbox:
        return {**result, "error_message": "沒有查詢範圍"}

    params = {
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "typeName": BUILDING_LAYER, "outputFormat": "application/json",
        "srsName": SRS, "maxFeatures": max(1, int(limit)),
        # WFS 1.0.0 的 BBOX 是 minx,miny,maxx,maxy，配合 srsName 就是經緯度
        "bbox": (f"{bbox['minlon']},{bbox['minlat']},"
                 f"{bbox['maxlon']},{bbox['maxlat']},{SRS}"),
    }
    try:
        resp = requests.get(f"{GEOSERVER}/wfs", params=params, timeout=30,
                            headers={"User-Agent": USER_AGENT})
    except requests.Timeout:
        return {**result, "error_message": "成大 GeoServer 查詢逾時"}
    except requests.RequestException as exc:
        return {**result, "error_message": f"無法連線成大 GeoServer（{type(exc).__name__}）"}

    if resp.status_code != 200:
        return {**result, "error_message": f"成大 GeoServer 回應 HTTP {resp.status_code}"}
    try:
        payload = resp.json()
    except ValueError:
        return {**result, "error_message": "成大 GeoServer 回應不是 JSON"}

    buildings = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        name = props.get("Name") or props.get("name") or props.get("BuildName") or ""
        center = _centroid(feature.get("geometry") or {})
        if name and center:
            buildings.append({"name": name, "lat": center[0], "lon": center[1]})
    return {**result, "status": "ok", "buildings": buildings}


def _centroid(geometry: dict) -> tuple[float, float] | None:
    """多邊形外接矩形的中心。夠用來當地標位置，不必算真正的形心。"""
    lats: list[float] = []
    lons: list[float] = []

    def walk(node) -> None:
        if (isinstance(node, (list, tuple)) and len(node) >= 2
                and all(isinstance(v, (int, float)) for v in node[:2])):
            lons.append(float(node[0]))
            lats.append(float(node[1]))
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(geometry.get("coordinates"))
    if not lats:
        return None
    return ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
