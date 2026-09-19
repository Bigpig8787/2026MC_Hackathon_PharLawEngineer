"""Skill 層：把「下一堂課在哪」和「哪裡還有車位」串成一個停車建議。

Tool 層各自獨立（查課表、查教室、查車位、查座標、組連結），這裡負責決策：
挑一個「離目的地夠近、而且車位夠多」的停車場，車位不足時自動換下一個。

停車系統只給停車場名稱與剩餘數，沒有座標，因此距離來自
data/parking_locations.json：那份對照表由 scripts/build_parking_locations.py
拿停車場名字去 GIS 反查同名大樓產生，不是人工填的。
對不到大樓的停車場（例如「林森路平面機車停車場」）不會被硬湊座標，
而是標成未知、排在最後，並如實告訴使用者無法計算距離。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from commute_agent.tools.ncku_geo import estimate_minutes, haversine_meters
from commute_agent.tools.ncku_parking import CAMPUS_CODES, get_parking_availability

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCATIONS_PATH = PROJECT_ROOT / "data" / "parking_locations.json"

# 使用者要求：車位少於這個數就別推薦，直接換下一個停車場
MIN_AVAILABLE = 30

# 「奇美樓地下機車停車場」→「奇美樓」，用來去 GIS 反查同名大樓
LOT_SUFFIX_RE = re.compile(r"(地下|平面)?(機車|汽車)停車場$")


def lot_base_name(lot_name: str) -> str:
    """把停車場名稱去掉「地下／平面＋車種＋停車場」的尾巴，留下地標名。"""
    return LOT_SUFFIX_RE.sub("", (lot_name or "").strip()).strip()


# 反查大樓時可以再退一步的尾綴：「雲平東側」→「雲平」、「理學大樓」→「理學」。
# 刻意不含「前門」「後門」「校區」「路」，因為那些是校門與道路，
# 再退一步只會比對到不相干的宿舍（查「光復」會撈到光復第三宿舍）。
TRIMMABLE_SUFFIXES = ("東側", "西側", "南側", "北側", "大樓")


def lot_name_candidates(lot_name: str) -> list[str]:
    """回傳反查 GIS 時要依序嘗試的關鍵字，由精確到寬鬆。"""
    base = lot_base_name(lot_name)
    candidates = [base]
    for suffix in TRIMMABLE_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            trimmed = base[: -len(suffix)]
            if trimmed not in candidates:
                candidates.append(trimmed)
    return candidates


def load_lot_locations(path: Path = LOCATIONS_PATH) -> dict[str, dict]:
    """讀停車場座標對照表；檔案不存在時回空 dict，讓呼叫端照樣能跑（只是沒有距離）。"""
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {row["lot_name"]: row for row in payload.get("lots", [])
            if row.get("lat") is not None and row.get("lon") is not None}


def rank_lots(lots: list[dict], dest_lat: float, dest_lon: float,
              travel_mode: str = "walking", min_available: int = MIN_AVAILABLE) -> list[dict]:
    """替停車場算出與目的地的距離並排序。純函式，座標由呼叫端先併好。

    排序規則：車位足夠的排前面（依距離近到遠），車位不足的排後面，
    連座標都查不到的排最後——不知道距離就不該假裝它很近。
    """
    ranked = []
    for lot in lots:
        lat, lon = lot.get("lat"), lot.get("lon")
        entry = {**lot, "distance_m": None, "minutes": None,
                 "enough_space": lot["available"] >= min_available}
        if lat is not None and lon is not None:
            distance = haversine_meters(dest_lat, dest_lon, lat, lon)
            entry["distance_m"] = round(distance)
            entry["minutes"] = estimate_minutes(distance, travel_mode)
        ranked.append(entry)

    def sort_key(entry: dict) -> tuple:
        unknown = entry["distance_m"] is None
        return (unknown, not entry["enough_space"],
                entry["distance_m"] if not unknown else 0)

    ranked.sort(key=sort_key)
    return ranked


def plan_parking(destination_building: str, vehicle_type: str,
                 walk_mode: str = "walking") -> dict:
    """替某棟大樓找出最近、而且車位夠多的成大停車場。

    適用時機：使用者要騎車或開車到某棟大樓上課，需要知道該停哪裡時使用。
    會掃過全校各校區的停車場，挑出離目的地最近、剩餘車位不少於 30 的那一個；
    車位不足的停車場會自動跳過，改推薦下一個最近的。

    Args:
        destination_building: 目的地大樓名稱，例如 "B501 資訊工程系館"。
            請用 lookup_room 回傳的 building_name，不要用課表上寫的名稱。
        vehicle_type: "機車" 或 "汽車"。
        walk_mode: 從停車場走到大樓的方式，預設 "walking"。

    Returns:
        dict，包含：
        - status: "ok"、"not_found"（完全沒有可用車位）或 "error"
        - recommended: 建議停的停車場，含 name、campus、available、
          distance_m（到目的地的直線距離）、minutes（步行分鐘數，估算值）
        - alternatives: 其他選項，依同樣規則排序
        - skipped_full: 因為車位少於 30 而被跳過的停車場名稱
        - destination: 目的地大樓的 GIS 名稱與座標
        - note: 資料限制說明（時間為估算值等）
    """
    from commute_agent.tools.ncku_geo import get_building_location

    place = get_building_location(destination_building)
    if place["status"] != "ok":
        return {"status": "error", "recommended": None, "alternatives": [],
                "error_message": f"查不到大樓座標：{destination_building}"}

    locations = load_lot_locations()
    lots: list[dict] = []
    for campus in CAMPUS_CODES:
        result = get_parking_availability(campus, vehicle_type)
        if result["status"] != "ok":
            continue
        for lot in result["lots"]:
            known = locations.get(lot["name"], {})
            lots.append({**lot, "lat": known.get("lat"), "lon": known.get("lon")})

    if not lots:
        return {"status": "not_found", "recommended": None, "alternatives": [],
                "error_message": f"查不到任何{vehicle_type}停車場"}

    ranked = rank_lots(lots, place["lat"], place["lon"], walk_mode)
    usable = [lot for lot in ranked if lot["enough_space"]]
    skipped = [lot["name"] for lot in ranked if not lot["enough_space"]]

    return {
        "status": "ok" if usable else "not_found",
        "destination": {"name": place["name"], "lat": place["lat"], "lon": place["lon"]},
        "recommended": usable[0] if usable else None,
        "alternatives": usable[1:6],
        "skipped_full": skipped,
        "min_available": MIN_AVAILABLE,
        "note": "距離為直線距離，時間為估算值（已乘上繞路係數），不含紅綠燈與實際路網。",
    }
