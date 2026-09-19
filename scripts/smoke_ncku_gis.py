"""在自己電腦上用 live 模式打真實的成大 GIS API。

用法：
    python scripts/smoke_ncku_gis.py 4264 65304 格致廳
    python scripts/smoke_ncku_gis.py --record 格致廳     # 同時存成 fixture
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PROVIDER_MODE"] = "live"

import requests  # noqa: E402

from api import load_settings  # noqa: E402
from commute_agent.tools import ncku_room  # noqa: E402


def record(query: str) -> None:
    s = load_settings()
    params = {"action": "search", "locale": "zh-tw", "q": query,
              "exactlyMatch": "false", "start": "0", "page": "1", "limit": "20"}
    resp = requests.get(s.ncku_gis_base_url + ncku_room.ROOMINFO_PATH, params=params,
                        timeout=s.http_timeout_seconds, headers={"User-Agent": ncku_room.USER_AGENT})
    resp.raise_for_status()
    path = ncku_room.FIXTURE_DIR / f"{query}.json"
    path.write_text(json.dumps(resp.json(), ensure_ascii=False), encoding="utf-8")
    print(f"已錄製 {path.name}（記得更新 fixtures/README.md）")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("queries", nargs="+")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    for q in args.queries:
        r = ncku_room.lookup_room(q)
        print(f"[{r['status']}] {q} → 完全相符 {r['exact_match_count']} 筆")
        for c in r["candidates"]:
            mark = "★" if c["exact_match"] else " "
            print(f"   {mark} {c['room_code'] or '-'} {c['room_name']}｜{c['building_name']} {c['floor']}")
        if r["status"] == "error":
            print(f"   錯誤：{r['error_message']}")
        if args.record:
            record(q)


if __name__ == "__main__":
    main()
