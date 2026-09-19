"""Tool 層：教室代碼推樓層，以及 picture/ 底下的平面圖截圖對照。

Tool 只負責「讀本地資料、整理格式」，不呼叫其他 Tool 或 Skill；
要把 GIS 查到的樓層跟這裡的推算對起來，是 Skill 的事。

樓層藏在教室代碼裡：大樓代號後面那一碼就是樓層。多數大樓代號是兩碼，
所以樓層是第三碼（27103 → A004 雲平大樓東棟 1F、
65304 → B502 資訊工程系大樓 3F）；
少數大樓代號只有一碼，樓層就落在第二碼（4264 → B501 資訊工程系館 2F、
7208 → 唯農大樓 2F）。這條規則只是推算 —— 成大 GIS 查得到時一律以 GIS 為準，
規則是查不到時才用的備援，而且要標明來源，不能讓使用者以為是官方資料。

平面圖是人工從 nckumap 截下來的圖，一張只涵蓋一棟大樓的一層。
nckumap 的平面圖圖層走 OpenLayers 向量繪製，沒有可以直接取圖的公開端點
（2026-09-19 實測 roominfo/buildinfo 都只回文字與座標），所以先用截圖對照表。
因此比對時樓層必須相符：拿三樓的圖去說二樓的教室在哪，比沒有圖更糟。
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "floor_plans.json"
PICTURE_DIR = PROJECT_ROOT / "picture"

# 網頁把 picture/ 掛在這個路徑底下
PICTURE_URL_PREFIX = "/picture"

# 這些大樓的代號只有一碼，樓層因此落在教室代碼的第二碼而非第三碼。
# 依 nckumap 實測：4264、4261 → B501 資訊工程系館 2F；7208 → A006 唯農大樓 2F。
# 注意「資訊系館」指的是資工這兩棟，跟 B003 資訊大樓是不同的建築。
ONE_DIGIT_BUILDING_PREFIXES = ("42", "72")

FLOOR_DIGIT_DEFAULT = 2          # 第三碼（0-based）
FLOOR_DIGIT_EXCEPTION = 1        # 第二碼（0-based）


def describe_floor(floor: str) -> str:
    """把 "2F"、"B1" 這種樓層代碼講成人話。"""
    text = (floor or "").strip().upper()
    if not text:
        return ""
    if text.startswith("B") and text[1:].isdigit():
        return f"地下 {int(text[1:])} 樓"
    digits = text.rstrip("F")
    return f"{int(digits)} 樓" if digits.isdigit() else text


def floor_from_room_code(room_code: str) -> dict:
    """用教室代碼推樓層。純函式，不查任何資料。

    Returns:
        dict，含 floor（推不出來時為 None）、digit_index（用了第幾碼，1-based）
        與 rule（這條規則的說明文字）。
    """
    code = (room_code or "").strip()
    if not code.isdigit() or len(code) < 3:
        return {"floor": None, "digit_index": None,
                "rule": "教室代碼不是純數字或太短，推不出樓層"}

    exception = code.startswith(ONE_DIGIT_BUILDING_PREFIXES)
    index = FLOOR_DIGIT_EXCEPTION if exception else FLOOR_DIGIT_DEFAULT
    digit = code[index]
    rule = (f"{code[:2]} 開頭的大樓代號只有一碼，樓層看第 {index + 1} 碼"
            if exception else f"大樓代號兩碼，樓層看第 {index + 1} 碼")

    if digit == "0":
        # 0 不是樓層。這通常代表這棟的代號長度跟規則假設的不一樣，
        # 硬湊出「0 樓」只會誤導，寧可回 None 讓呼叫端去問 GIS
        return {"floor": None, "digit_index": index + 1,
                "rule": f"{rule}，但該碼是 0，推不出樓層"}
    return {"floor": f"{digit}F", "digit_index": index + 1, "rule": rule}


def load_manifest() -> dict:
    """讀 picture/ 的平面圖對照表。檔案不存在時回空表，不讓呼叫端炸掉。"""
    if not MANIFEST_PATH.is_file():
        return {"campus_map": None, "plans": []}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _as_image(entry: dict) -> dict:
    return {"file": entry["file"],
            "url": f"{PICTURE_URL_PREFIX}/{entry['file']}",
            "caption": entry.get("caption", ""),
            "available": (PICTURE_DIR / entry["file"]).is_file()}


def _matches(entry: dict, code: str, name: str, floor: str) -> bool:
    if code and code in entry.get("rooms", []):
        return True
    if name and any(k in name for k in entry.get("name_keywords", [])):
        return True
    prefix = entry.get("room_prefix") or ""
    if prefix and code.startswith(prefix):
        # 只有同一層才算命中：42.png 是 2F，拿它說 4364 在哪層是錯的
        return bool(floor) and floor.upper() == entry["floor"].upper()
    return False


def get_floor_plan(room_code: str = "", room_name: str = "", floor: str = "") -> dict:
    """找出某間教室那一層的平面圖截圖，並推算它在幾樓。

    適用時機：使用者問「教室長怎樣」、「在幾樓」、「怎麼找教室」，
    或要在畫面上標出平面圖時使用。

    Args:
        room_code: 教室代碼，例如 "4264"、"27103"。
        room_name: 教室名稱，例如 "格致廳小講堂"。代碼查不到時用名稱比對。
        floor: 已知的樓層（例如成大 GIS 回的 "2F"）。留空則用代碼推算。

    Returns:
        dict，包含：
        - status: "ok"（有平面圖）或 "not_found"（這一層沒有收錄的圖）
        - floor: 最後採用的樓層；floor_source 標明是 "given"（呼叫端給的）
          還是 "room_code"（由代碼推算）
        - floor_rule: 推算規則的說明，供介面標示這是推算而非官方資料
        - plan: 平面圖的 file、url、caption 與 available（檔案是否真的在）
        - campus_map: 校區全圖，讓使用者先知道大樓在校園哪個位置
    """
    code = (room_code or "").strip()
    name = (room_name or "").strip()
    manifest = load_manifest()

    guess = floor_from_room_code(code)
    used_floor = (floor or "").strip() or (guess["floor"] or "")
    source = "given" if (floor or "").strip() else ("room_code" if guess["floor"] else None)

    campus = manifest.get("campus_map")
    result = {
        "status": "not_found",
        "room_code": code,
        "room_name": name,
        "floor": used_floor or None,
        "floor_source": source,
        "floor_rule": guess["rule"],
        "floor_by_room_code": guess["floor"],
        "plan": None,
        "campus_map": _as_image(campus) if campus else None,
    }

    for entry in manifest.get("plans", []):
        if _matches(entry, code, name, used_floor):
            return {**result, "status": "ok", "plan": _as_image(entry),
                    "plan_floor": entry["floor"],
                    "plan_building": entry.get("building_name", "")}

    result["error_message"] = (
        f"picture/ 裡沒有收錄 {code or name or '這間教室'} 所在樓層的平面圖")
    return result
