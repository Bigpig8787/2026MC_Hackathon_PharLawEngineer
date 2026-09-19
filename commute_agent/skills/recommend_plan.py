"""Skill 層：讓 Gemini 在各交通方案之間做取捨，並說明理由。

compare_plans 負責把四種方式的時間與風險整理成結構化資料，那是查詢；
要在「快 6 分鐘但要淋雨」和「慢一點但不會遲到」之間選一個，則是帶個人偏好
的主觀判斷，寫成排序函式只會變成一組拍腦袋的權重。這支把選擇權交給模型，
並把 COMMUTE_PREFERENCE 那句話一起丟進去，讓同樣的資料對不同人給出不同建議。

權衡的軸有三條：準時、天氣與體感溫度帶來的舒適度、以及碳排。碳排寫成
MODE_FOOTPRINT 常數而非交給模型自由發揮，因為各方式的高低順序是確定的；
但「值不值得為低碳排多花十分鐘」仍然是判斷，所以留在 prompt 裡由模型決定。
準時是硬性條件，不會被環保壓過去 —— 遲到的代價落在使用者身上。

兩個刻意的限制：

- 用 response_schema 要求固定 JSON。自由文字前端沒法穩定顯示，也無法驗證
  模型選的模式真的在選項裡。
- 模型失敗（額度用盡、逾時、選了不存在的模式）一律退回 compare_plans 的
  規則排序，並標明 source="rules"，不讓畫面開天窗，也不假裝那是 AI 建議。
"""

from __future__ import annotations

import json
from datetime import datetime

from api import load_settings
from commute_agent.skills.compare_plans import compare_plans
from commute_agent.tools.gemini_error import describe

# 只把模型判斷需要的欄位丟過去：座標、連結、逐段明細對取捨沒有幫助，
# 塞進 prompt 只會變貴又容易讓它分心
PROMPT_FIELDS = ("mode", "label", "minutes", "leave_by", "late_by", "risks", "weather")

# 各方式的碳排級距。寫成常數而不是讓模型自己想：模型對「機車比公車環保嗎」
# 這種事會給出不穩定的答案，但這個排序是確定的，直接寫進 prompt 比較可靠。
# 不給精確的 gCO2/km —— 那需要車種、載客率、電力結構，我們沒有這些資料。
MODE_FOOTPRINT = {
    "walking": "零碳排，完全不耗能",
    "bicycling": "零碳排（YouBike 為共享單車）",
    "transit": "低碳排，公車多載一人幾乎不增加排放",
    "driving": "碳排最高，機車與汽車都是一人一車",
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "chosen_mode": {"type": "string",
                        "description": "選中的交通方式代碼，必須是選項中出現過的 mode"},
        "reason": {"type": "string",
                   "description": "一到兩句話說明為什麼選它，要提到具體數字或風險"},
        "warnings": {"type": "array", "items": {"type": "string"},
                     "description": "使用者出發前該注意的事，沒有就給空陣列"},
    },
    "required": ["chosen_mode", "reason"],
}

INSTRUCTION = """你是替成大學生規劃通勤的助理。下面是同一趟路的幾個交通方案，
已經算好各自的路程時間、最晚出發時刻、出發當下的天氣與風險。
請在「準時、舒適、環保」三者之間權衡，選出最適合的一個。

硬性條件（不滿足就不能選）：
- minutes 為 null 代表這個方式現在不可行（例如附近沒有可借的車），不可以選它。
- 會遲到的方案除非別無選擇，否則不要選（late_by 大於 0 代表已經超過最晚出發時刻）。
  準時優先於環保，不要為了少一點碳排讓使用者遲到。

天氣與溫度（weather 欄位是「該方案出發時刻」的預報，不是現在的天氣）：
- rain_probability 高或 will_rain 為 true 時，步行、自行車、機車都會淋濕；
  路程愈長淋得愈久，這時有遮蔽的公車值得多花幾分鐘。
- apparent_temperature（體感溫度）是判斷是否適合曝曬在外的依據：
  體感約 32 度以上會流汗、35 度以上有中暑風險，體感偏低（約 15 度以下）
  騎車會冷；這種天氣下長距離的步行或騎乘要謹慎推薦，短程則影響不大。
- weather 為 null 代表查不到預報，就照實說沒有天氣資料，不可以自己假設晴天。
  rain_probability 為 null 同樣不等於不會下雨。

環保（碳排由低到高）：
{footprint}
- 在同樣趕得上、天氣也撐得住的方案之間，優先選碳排較低的那個。
- 時間差距不大（大約 10 分鐘以內）時，值得為了低碳排多花這幾分鐘，
  並在理由中說明這個取捨。差距很大時就以時間與舒適度為準。
- 風險要實際權衡，不是一律避開：車位剩很多時「可能已滿」不算大問題。

回答要求：
- 理由要講具體數字（幾分鐘、幾度、降雨機率幾 %），不要只說「比較快」或「比較環保」。
- 為了環保而沒選最快的方案時，要明講多花了幾分鐘換到什麼。
- user_preference 是這位使用者自己的偏好，與上述原則衝突時以他的偏好為準。
""".format(footprint="\n".join(f"- {label}：{note}"
                               for label, note in MODE_FOOTPRINT.items()))


# 偏好是使用者自己輸入、會原樣放進 prompt 的文字，限制長度避免拿來塞一大段指令
MAX_PREFERENCE_CHARS = 300


def _payload(result: dict, preference: str) -> str:
    options = [{k: option.get(k) for k in PROMPT_FIELDS}
               for option in result["options"]]
    return json.dumps({
        "course": result["course"],
        "class_starts_at": result["class_starts_at"],
        "now": result["now"],
        "user_preference": preference or "（未提供個人偏好，只看時間與風險）",
        "options": options,
    }, ensure_ascii=False, indent=2)


def _fallback(result: dict, reason: str) -> dict:
    best = result.get("best")
    return {
        "status": "ok",
        "source": "rules",
        "chosen_mode": best["mode"] if best else None,
        "reason": f"（規則排序，非 AI 建議）{reason}",
        "warnings": list(best["risks"]) if best else [],
        "comparison": result,
    }


def recommend_plan(origin: str = "", vehicle_type: str = "機車",
                   schedule_path: str = "", preference: str = "",
                   now: datetime | None = None) -> dict:
    """比較各交通方式後，交給 Gemini 選出最適合的一個並說明理由。

    適用時機：使用者問「我今天該怎麼去」、「下雨要搭什麼」這類需要權衡的問題。
    單純想看各方案數字時用 compare_plans 就好，不必花這次模型呼叫。

    Args:
        origin: 出發地。留空則用 .env 的 DEFAULT_ORIGIN。
        vehicle_type: 開車模式要停的車種，"機車" 或 "汽車"。
        schedule_path: 要依哪一份課表建議，留空表示用預設課表。
        preference: 這位使用者的通勤偏好（一句話）。留空則用 .env 的
            COMMUTE_PREFERENCE；網頁讓使用者自己設定並帶進來。
        now: 用哪個時間當「現在」，留空是真實時間（網頁的模擬時間靠它）。

    Returns:
        dict，包含：
        - status: "ok"、"no_class" 或 "error"
        - source: "gemini"（模型建議）或 "rules"（模型失敗時的規則排序）
        - chosen_mode、reason、warnings: 建議的方式、理由與注意事項
        - comparison: compare_plans 的完整結果，供介面顯示各方案細節
    """
    settings = load_settings()
    # 只有明確指定時才傳 now，舊的呼叫端與測試替身不必跟著改簽名
    result = compare_plans(origin, vehicle_type, schedule_path,
                           **({"now": now} if now is not None else {}))
    preference = (preference or settings.commute_preference or "").strip()[:MAX_PREFERENCE_CHARS]
    if result["status"] != "ok":
        return {**result, "source": "rules", "chosen_mode": None,
                "reason": "", "warnings": []}

    if not settings.gemini_api_key:
        return _fallback(result, "尚未設定 Gemini 金鑰。")

    from google import genai
    from google.genai import types

    # client 必須留在變數裡：寫成 genai.Client(...).models.generate_content(...)
    # 的話，暫時物件會在請求送出前被回收，連線關掉後丟出
    # 「Cannot send a request, as the client has been closed」
    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[INSTRUCTION, _payload(result, preference)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA),
        )
        answer = json.loads(response.text or "{}")
    except Exception as exc:  # SDK 會丟各種自訂例外，額度用盡也走這裡
        return _fallback(result, f"{describe(exc)}。")

    chosen = answer.get("chosen_mode")
    valid = {option["mode"] for option in result["options"]
             if option["minutes"] is not None}
    if chosen not in valid:
        # 模型選了不存在或不可行的方式，這種回答不能拿來顯示
        return _fallback(result, f"Gemini 選了無法使用的方式（{chosen!r}）。")

    return {
        "status": "ok",
        "source": "gemini",
        "chosen_mode": chosen,
        "reason": answer.get("reason", ""),
        "warnings": answer.get("warnings") or [],
        "comparison": result,
    }
