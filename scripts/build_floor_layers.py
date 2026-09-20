"""把成大 GeoServer 的樓層平面圖清單抓下來，存成本地索引。

成大地圖（nckumap.ncku.edu.tw/map.php）的平面圖不是圖片檔，是 GeoServer 的
WMS 圖層：每一棟每一層一個圖層，命名規則為 gis_room:<大樓代碼>_<樓層>
（例如 gis_room:B029_2F）。這支把 GetCapabilities 裡那一千多個圖層的名稱與
範圍整理成 data/ncku_floor_layers.json，之後就能離線知道「這棟有哪幾層」，
以及每一層的圖要用哪個 bbox 去要，不必每次下載 1.6MB 的 XML。

重建：
    ./.venv/bin/python scripts/build_floor_layers.py
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "ncku_floor_layers.json"

GEOSERVER = "https://db.nckumap.ncku.edu.tw/geoNckuGis"
WORKSPACE = "gis_room"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"


def fetch_capabilities() -> bytes:
    resp = requests.get(f"{GEOSERVER}/wms",
                        params={"service": "WMS", "version": "1.1.1",
                                "request": "GetCapabilities"},
                        timeout=120, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content


def parse_layers(xml_bytes: bytes) -> dict:
    """抽出 gis_room 工作區底下的圖層，依大樓代碼分組。

    每一層記下 EPSG:3826 的範圍：WFS 回的幾何也是 3826，兩邊同一套座標，
    算「這間教室在圖上的哪個位置」時就不必再投影一次。
    """
    root = ET.fromstring(xml_bytes)
    buildings: dict[str, dict] = {}

    for layer in root.iter("Layer"):
        name = layer.findtext("Name") or ""
        if not name.startswith(f"{WORKSPACE}:") or "_" not in name:
            continue
        build_id, _, floor = name.split(":", 1)[1].rpartition("_")
        if not build_id or not floor:
            continue

        box = None
        for candidate in layer.iter("BoundingBox"):
            if candidate.get("SRS") == "EPSG:3826":
                box = [float(candidate.get(k)) for k in ("minx", "miny", "maxx", "maxy")]
                break
        if box is None:
            continue

        buildings.setdefault(build_id, {})[floor] = box

    return buildings


def main() -> None:
    buildings = parse_layers(fetch_capabilities())
    payload = {
        "note": ("成大 GeoServer 的樓層平面圖圖層索引，由 scripts/build_floor_layers.py "
                 "產生。bbox 為 EPSG:3826（TWD97 二度分帶），與 WFS 回的幾何同一套座標。"),
        "geoserver": GEOSERVER,
        "workspace": WORKSPACE,
        "buildings": buildings,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    floors = sum(len(v) for v in buildings.values())
    print(f"{len(buildings)} 棟大樓、{floors} 個樓層 → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
