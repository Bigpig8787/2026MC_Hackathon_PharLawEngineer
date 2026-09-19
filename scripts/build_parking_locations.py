"""產生 data/parking_locations.json：停車場名稱 → 經緯度。

停車系統只給停車場名稱與剩餘車位，沒有座標。這支腳本把停車場名字去掉
「地下／平面＋車種＋停車場」的尾巴後（例如「奇美樓地下機車停車場」→「奇美樓」），
拿去成大 GIS 反查同名大樓的中心點，當作停車場的近似座標。

反查不到的（例如「林森路平面機車停車場」這種以路名命名的）會留 lat/lon 為 null，
不會亂填座標；執行時會列出來，方便人工判斷要不要補。

用法：
    ./.venv/bin/python scripts/build_parking_locations.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PROVIDER_MODE"] = "live"

from commute_agent.skills.parking_plan import lot_name_candidates  # noqa: E402
from commute_agent.tools.ncku_geo import get_building_location  # noqa: E402
from commute_agent.tools.ncku_parking import CAMPUS_CODES, get_parking_availability  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "parking_locations.json"


def collect_lots() -> list[dict]:
    seen: dict[str, dict] = {}
    for campus in CAMPUS_CODES:
        for vehicle in ("機車", "汽車"):
            result = get_parking_availability(campus, vehicle)
            if result["status"] != "ok":
                print(f"  ! {campus}{vehicle} 查詢失敗：{result.get('error_message')}")
                continue
            for lot in result["lots"]:
                seen.setdefault(lot["name"], {"lot_name": lot["name"], "campus": lot["campus"]})
    return sorted(seen.values(), key=lambda r: r["lot_name"])


def main() -> None:
    lots = collect_lots()
    print(f"共 {len(lots)} 個停車場，開始反查座標…\n")

    resolved, unresolved = 0, []
    for lot in lots:
        candidates = lot_name_candidates(lot["lot_name"])
        hit = None
        for candidate in candidates:
            place = get_building_location(candidate)
            if place["status"] == "ok":
                hit = (candidate, place)
                break
        if hit:
            candidate, place = hit
            lot.update(lat=place["lat"], lon=place["lon"], matched_query=candidate,
                       matched_building=place["name"], build_id=place["build_id"])
            resolved += 1
            print(f"  ok  {lot['lot_name']}  →  {place['name']}（查 {candidate}）")
        else:
            lot.update(lat=None, lon=None, matched_query="",
                       matched_building="", build_id="")
            unresolved.append(lot["lot_name"])
            print(f"  --  {lot['lot_name']}  →  查無（試過 {'、'.join(candidates)}）")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(
        {"note": "由 scripts/build_parking_locations.py 反查 GIS 產生，座標為同名大樓中心點",
         "lots": lots}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n已寫入 {OUTPUT}")
    print(f"成功 {resolved} / {len(lots)}，查無座標 {len(unresolved)} 個：")
    for name in unresolved:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
