"""Skill 層：拍教室門牌或樓層指示牌，告訴你「現在在哪、目標教室在哪」。

大樓裡最後那一段最容易迷路：導航把人帶到大樓門口就結束了，樓層與教室得自己找，
而且成大有兩棟資工大樓、走廊上的編號不一定照直覺排。

分工跟其他用到 Gemini 的地方一樣：模型只負責「讀出照片上的字」，
讀到的代碼一律回成大 GIS 驗證（lookup_room），查得到才算數。
模型讀錯一個數字不會讓人被帶到別間——查不到就照實說沒認出來，
不會拿沒驗證過的答案當真。樓層關係也是由 GIS 給的樓層算的，不是模型說的。
"""

from __future__ import annotations

import json
import re

from api import load_settings
from commute_agent.tools.gemini_error import describe
from commute_agent.tools.ncku_room import lookup_room
from commute_agent.tools.schedule_ocr import MAX_IMAGE_BYTES, SUPPORTED_MIME_TYPES

MAX_CODES = 3

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "room_codes": {
            "type": "array", "items": {"type": "string"},
            "description": "照片上實際看得到的教室代碼或教室名稱，最清楚的排前面，最多三個"},
        "building_text": {"type": "string", "description": "照片上寫的大樓名稱，看不到給空字串"},
        "floor_text": {"type": "string", "description": "照片上寫的樓層，例如 2F，看不到給空字串"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "note": {"type": "string", "description": "一句話說明你讀到了什麼、哪裡看不清楚"},
    },
    "required": ["room_codes"],
}

INSTRUCTION = """這是成功大學校園裡的一張現場照片，可能拍到教室門牌、走廊的樓層指示，
或系館的導覽牌。請只讀出照片上「實際看得到」的文字：

- room_codes：教室代碼（成大是 4 到 5 位數字，例如 4264、27103）或教室名稱
  （例如「格致廳」）。最清楚的排最前面，最多三個。
- building_text：照片上寫的大樓名稱；看不到就給空字串。
- floor_text：照片上寫的樓層；看不到就給空字串。
- confidence：整體有多確定。

看不清楚的數字就不要寫，寧可給空陣列，也不要猜或補完。
你的輸出之後會拿去成大地理資訊系統驗證，猜錯的代碼只會白費一次查詢。
"""


class SignError(RuntimeError):
    """讀取門牌的流程失敗（缺金鑰、模型無法回應、回傳無法解析）。"""


def _ask_gemini(image_bytes: bytes, mime_type: str) -> dict:
    """把照片交給 Gemini，回傳解析後的 JSON。失敗一律丟 SignError。"""
    settings = load_settings()
    if not settings.gemini_api_key:
        raise SignError("尚未設定 GOOGLE_API_KEY／GEMINI_API_KEY，無法辨識照片")

    from google import genai
    from google.genai import types

    # client 必須留在變數裡，否則暫時物件會在請求送出前被回收
    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                      INSTRUCTION],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA),
        )
        return json.loads(response.text or "{}")
    except Exception as exc:  # SDK 會丟各種自訂例外，額度用盡也走這裡
        raise SignError(describe(exc)) from exc


def read_room_sign(image_bytes: bytes, mime_type: str) -> dict:
    """讀出照片上的教室代碼。只做辨識，不驗證。

    Returns:
        dict，含 status（"ok" 或 "error"）、room_codes、building_text、
        floor_text、confidence、note；失敗時含 error_message。
    """
    empty = {"room_codes": [], "building_text": "", "floor_text": "",
             "confidence": "low", "note": ""}
    if mime_type not in SUPPORTED_MIME_TYPES:
        return {**empty, "status": "error",
                "error_message": f"不支援的圖片格式 {mime_type!r}，"
                                 f"請改用 {'、'.join(sorted(SUPPORTED_MIME_TYPES))}"}
    if not image_bytes:
        return {**empty, "status": "error", "error_message": "圖片是空的"}
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return {**empty, "status": "error",
                "error_message": f"圖片超過 {MAX_IMAGE_BYTES // 1024 // 1024} MB 上限"}

    try:
        answer = _ask_gemini(image_bytes, mime_type)
    except SignError as exc:
        return {**empty, "status": "error", "error_message": str(exc)}

    codes: list[str] = []
    for item in answer.get("room_codes") or []:
        code = str(item).strip()
        if code and len(code) <= 30 and code not in codes:
            codes.append(code)

    confidence = answer.get("confidence")
    return {"status": "ok", "room_codes": codes[:MAX_CODES],
            "building_text": str(answer.get("building_text") or "").strip(),
            "floor_text": str(answer.get("floor_text") or "").strip(),
            "confidence": confidence if confidence in ("high", "medium", "low") else "low",
            "note": str(answer.get("note") or "").strip()}


def floor_level(floor: str | None) -> int | None:
    """樓層字串轉成可比較的整數：3F→3、B1／B1F→-1；認不得的回 None。"""
    match = re.fullmatch(r"(B)?(\d{1,2})F?", (floor or "").strip().upper())
    if not match:
        return None
    level = int(match.group(2))
    return -level if match.group(1) else level


def relate(here: dict, target: dict) -> dict:
    """依 GIS 給的大樓與樓層，說明「目標教室相對現在的位置」。純函式。"""
    if here["building_id"] and target["building_id"] and here["building_id"] != target["building_id"]:
        return {"kind": "other_building", "floors": None,
                "text": f"你現在在{here['building_name']}，要去的 {target['room_code']} "
                        f"在{target['building_name']}，得先走到另一棟。"}

    here_level, target_level = floor_level(here["floor"]), floor_level(target["floor"])
    if here_level is None or target_level is None:
        return {"kind": "unknown", "floors": None,
                "text": f"{target['room_code']} 跟你在同一棟大樓，但樓層資料不全，"
                        "請看樓層指示牌。"}

    diff = target_level - here_level
    if diff == 0:
        return {"kind": "same_floor", "floors": 0,
                "text": f"{target['room_code']} 就在這一層（{target['floor']}），沿走廊找。"}
    direction = "上" if diff > 0 else "下"
    return {"kind": "up" if diff > 0 else "down", "floors": diff,
            "text": f"{target['room_code']} 在{target['floor']}，要往{direction} {abs(diff)} 層。"}


def _verified(code: str) -> dict | None:
    """教室代碼回 GIS 驗證；只認完全相符的，模糊結果不採用。"""
    found = lookup_room(code)
    if found["status"] != "ok":
        return None
    exact = [c for c in found["candidates"] if c["exact_match"]]
    if not exact:
        return None
    room = exact[0]
    return {"room_code": room["room_code"] or code, "room_name": room["room_name"],
            "building_id": room["building_id"], "building_name": room["building_name"],
            "floor": room["floor"] or None}


def scan_room_sign(image_bytes: bytes, mime_type: str, target_room: str = "") -> dict:
    """拍門牌找教室：認出你現在在哪一間，並說明目標教室相對的位置。

    Args:
        image_bytes、mime_type: 門牌或樓層指示牌的照片。
        target_room: 要去的教室代碼（例如下一堂課的教室）；沒有就只回你在哪。

    Returns:
        dict，包含：
        - status: "ok"、"not_recognized"（讀到了字但成大查不到）或 "error"
        - sign: 模型讀到的原始文字（room_codes、building_text、floor_text、confidence）
        - here: 經 GIS 驗證的目前所在教室；沒驗證到為 None
        - target: 經 GIS 驗證的目標教室；沒給或查不到為 None
        - relation: 目標相對現在的位置（同層、往上幾層、另一棟…）與一句說明
    """
    sign = read_room_sign(image_bytes, mime_type)
    if sign["status"] != "ok":
        return {"status": "error", "error_message": sign["error_message"], "sign": sign,
                "here": None, "target": None, "relation": None}

    here = next((v for v in (_verified(c) for c in sign["room_codes"]) if v), None)
    target = _verified(target_room.strip()) if (target_room or "").strip() else None

    if here is None:
        seen = "、".join(sign["room_codes"]) or "沒有讀到任何代碼"
        return {"status": "not_recognized", "sign": sign, "here": None, "target": target,
                "relation": None,
                "note": f"照片上讀到：{seen}。成大地理資訊系統查不到對應的教室，"
                        "請靠近一點、讓門牌填滿畫面再拍一次。"}

    relation = relate(here, target) if target else None
    return {"status": "ok", "sign": sign, "here": here, "target": target,
            "relation": relation}
