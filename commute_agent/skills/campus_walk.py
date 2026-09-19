"""Skill 層：把「停好車之後怎麼走到教室」畫在校區圖上。

停車場到大樓這一段是整趟通勤裡最容易迷路的：導航把人帶到停車場就結束了，
剩下的兩三百公尺得自己在校園裡找路，而校園裡沒有門牌。

這支把三種資料兜成一張圖與一段話：

- 路線來自 Google Routes（成大地圖網站自己也是用 Google 規劃路徑的），
  取 encodedPolyline 解成一串座標。
- 底圖來自成大 GeoServer 的校區圖層，帶建物名稱，跟那張全校圖同一個來源。
  兩邊都用 EPSG:4326，所以路線點可以直接線性換算成圖片上的百分比位置。
- 指路文字交給 Gemini，但**地標清單是先用 WFS 查出來的**：只准它用路線附近
  真的存在的建物名稱。模型很會把路線講成人話，卻也很會憑空生出「經過活動中心」
  這種校園裡沒有、或根本不在這條路上的地標，所以地標由資料決定，語氣交給它。

Google 金鑰沒設或路線算不出來時，退回起訖兩點的直線，並標明 is_real_path=False
——讓人知道這只是方向示意，不是真的走得通的路。
"""

from __future__ import annotations

import json
import re
import time

from api import load_settings
from commute_agent.tools.gemini_error import describe, is_retryable
from commute_agent.tools.google_routes import compute_route
from commute_agent.tools.ncku_campus_map import (bbox_for, buildings_in_bbox,
                                                 campus_map_url, to_percent)

# 給模型的地標數量。太多它會每個都提一遍，反而看不出重點
MAX_LANDMARKS = 12

# Gemini 在尖峰時段會回 503 high demand，過一下就好。
# 重試一次換來的成功率值得那兩秒，再多就是讓使用者乾等
GEMINI_ATTEMPTS = 2
GEMINI_RETRY_SECONDS = 2.0

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array", "items": {"type": "string"},
            "description": "兩到四句指路，每句一個動作，要提到清單裡的地標名稱"},
        "summary": {"type": "string", "description": "一句話總結這段路"},
    },
    "required": ["steps", "summary"],
}

INSTRUCTION = """你在替成功大學的學生指路：他把車停好了，要從停車場走到上課的大樓。

我會給你這段路的距離、需要幾分鐘，以及沿路附近**真實存在**的建物清單
（含各自的經緯度，路線的起點與終點也一併給你）。

請寫兩到四句指路：

- 只能提到我給你的建物清單裡的名稱。清單以外的地標一律不准出現，
  就算你覺得成大應該有那棟樓也不行——講錯地標會讓人走反方向。
- 用「往北走」「在某某大樓前右轉」這種實際做得到的動作，
  不要講「往東北東方向前進 137 公尺」這種看了也不知道怎麼走的句子。
- 方向請依座標自己判斷：緯度變大是往北，經度變大是往東。
- 最後一句要讓人知道抵達了。
- 清單裡沒有合適的地標時，就只講方向與距離，不要硬湊。
"""


def _landmarks(points: list[tuple[float, float]], bbox: dict) -> list[dict]:
    """路線附近的建物，取離路線最近的幾棟。"""
    found = buildings_in_bbox(bbox)
    if found["status"] != "ok":
        return []

    def nearest(building: dict) -> float:
        return min((building["lat"] - lat) ** 2 + (building["lon"] - lon) ** 2
                   for lat, lon in points)

    return sorted(found["buildings"], key=nearest)[:MAX_LANDMARKS]


def describe_walk(lot_name: str, building_name: str, minutes: int | None,
                  distance_m: int | None, points: list[tuple[float, float]],
                  landmarks: list[dict]) -> dict:
    """請 Gemini 把路線講成指路的話。失敗時回空步驟，不丟例外。"""
    settings = load_settings()
    if not settings.gemini_api_key:
        return {"steps": [], "summary": "", "source": "none",
                "note": "尚未設定 Gemini 金鑰"}

    payload = {
        "from": lot_name, "to": building_name,
        "minutes": minutes, "distance_m": distance_m,
        "start": {"lat": points[0][0], "lon": points[0][1]} if points else None,
        "end": {"lat": points[-1][0], "lon": points[-1][1]} if points else None,
        "landmarks": landmarks,
    }

    from google import genai
    from google.genai import types

    # client 要留在變數裡，否則暫時物件會在請求送出前被回收
    client = genai.Client(api_key=settings.gemini_api_key)
    last_error = ""
    answer = None
    for attempt in range(GEMINI_ATTEMPTS):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=[INSTRUCTION, json.dumps(payload, ensure_ascii=False, indent=2)],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA),
            )
            answer = json.loads(response.text or "{}")
            last_error = ""
            break
        except Exception as exc:  # 額度用盡、逾時、SDK 自訂例外都走這裡
            last_error = describe(exc)
            if not is_retryable(exc):
                # 額度用完或金鑰不對，再試只是讓使用者多等兩秒看同一個錯
                break
            if attempt + 1 < GEMINI_ATTEMPTS:
                # 503 high demand 這種過一下再試多半就過了
                time.sleep(GEMINI_RETRY_SECONDS)
    if answer is None:
        return {"steps": [], "summary": "", "source": "none",
                "note": f"沒有指路文字：{last_error}"}

    allowed = {b["name"] for b in landmarks}
    steps = [s for s in (answer.get("steps") or []) if isinstance(s, str)]
    # 模型提到清單以外的建物時整段作廢：錯的地標比沒有地標更會害人走錯
    invented = [name for name in _mentioned_buildings(steps, allowed)]
    if invented:
        return {"steps": [], "summary": "", "source": "none",
                "note": f"Gemini 提到了路線附近沒有的地標（{'、'.join(invented)}）"}

    return {"steps": steps, "summary": answer.get("summary", ""),
            "source": "gemini", "note": ""}


# 成大的建物幾乎都以這幾個字結尾。寫寬一點無妨：誤標的代價只是捨掉這段指路，
# 漏標的代價卻是把人往根本不存在的地標帶
BUILDING_WORD = re.compile(
    r"[\u4e00-\u9fff]{2,8}(?:大樓|系館|學館|講堂|中心|廣場|廳|館|堂)")

# 名稱短於這個長度就不比對：「館」「系館」誰都對得上，比了沒有意義
MIN_NAME_PIECE = 3


def _is_known_landmark(mention: str, allowed: set[str]) -> bool:
    """這個名稱是不是清單裡那幾棟其中之一。

    正規表示式會把「從」「經過」這類動詞一起抓進來（「從三系館」），
    所以要逐字剝掉開頭再比；反過來模型也可能只講簡稱（「三系館」對
    「三系館鋼構區」），因此兩個方向都算相符。
    """
    for start in range(max(1, len(mention) - MIN_NAME_PIECE + 1)):
        piece = mention[start:]
        if len(piece) >= MIN_NAME_PIECE and any(piece in name for name in allowed):
            return True
    return any(name in mention for name in allowed)


def _mentioned_buildings(steps: list[str], allowed: set[str]) -> list[str]:
    """挑出句子裡看起來是建物、卻不在允許清單裡的名稱。

    只檢查「⋯⋯大樓／系館／館／廳」這種明顯的建物寫法：要求模型完全不提
    任何專有名詞會讓指路變得很空泛，但講到建物就必須是真的存在的那幾棟。
    """
    suspicious = [match for step in steps for match in BUILDING_WORD.findall(step)
                  if not _is_known_landmark(match, allowed)]
    return sorted(set(suspicious))


def plan_campus_walk(lot_name: str, lot_lat: float, lot_lon: float,
                     building_name: str, building_lat: float, building_lon: float,
                     width: int = 1200, height: int = 760) -> dict:
    """畫出從停車場走到某棟大樓的路線，並附上指路文字。

    適用時機：使用者騎車或開車上課，停好車之後要知道怎麼走到教室時使用。

    Args:
        lot_name、lot_lat、lot_lon: 停車場名稱與座標。
        building_name、building_lat、building_lon: 目的大樓名稱與座標。
        width、height: 校區圖的尺寸。

    Returns:
        dict，包含：
        - status: "ok" 或 "error"
        - map: 校區底圖的 url、bbox 與尺寸，可直接放進 <img src>
        - path: 路線在圖上的百分比座標清單，供前端畫線
        - from_point、to_point: 起訖點在圖上的百分比位置
        - minutes、distance_m: 這段路要走多久、多遠
        - is_real_path: True 代表是 Google 算出的實際路徑；
          False 代表只是起訖直線，僅供辨認方向
        - directions: Gemini 依真實地標寫出的指路文字（steps、summary）
        - landmarks: 路線附近真實存在的建物，指路只會用到這些
    """
    if None in (lot_lat, lot_lon, building_lat, building_lon):
        return {"status": "error", "error_message": "停車場或大樓缺少座標，畫不出路線"}

    route = compute_route((lot_lat, lot_lon), (building_lat, building_lon),
                          "walking", with_path=True)
    points = route.get("points") or []
    is_real_path = route["status"] == "ok" and len(points) >= 2
    if not is_real_path:
        # 直線不是真的路，但至少看得出往哪個方向走；一定要標明出來
        points = [(lot_lat, lot_lon), (building_lat, building_lon)]

    bbox = bbox_for(points, width, height)
    image = campus_map_url(bbox, width, height)
    landmarks = _landmarks(points, bbox)

    minutes = route.get("minutes") if is_real_path else None
    distance_m = route.get("distance_m") if is_real_path else None
    directions = describe_walk(lot_name, building_name, minutes, distance_m,
                               points, landmarks)

    return {
        "status": "ok",
        "from": lot_name,
        "to": building_name,
        "map": image,
        "path": [to_percent(lat, lon, bbox) for lat, lon in points],
        "from_point": to_percent(points[0][0], points[0][1], bbox),
        "to_point": to_percent(points[-1][0], points[-1][1], bbox),
        "minutes": minutes,
        "distance_m": distance_m,
        "is_real_path": is_real_path,
        "note": ("" if is_real_path else
                 f"Google 算不出步行路線（{route.get('error_message', '原因不明')}），"
                 "圖上畫的是起訖直線，只能看方向，不是真的走得通的路。"),
        "directions": directions,
        "landmarks": landmarks,
    }
