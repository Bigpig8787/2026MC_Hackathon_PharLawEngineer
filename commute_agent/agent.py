"""Step 0 煙霧測試用的最小 Agent。

目的只有一個：確認 ADK + Gemini + 真實 Tool 呼叫整條線能通。
Step 5 會以正式的 Application 層（主 Agent + SkillToolset）取代本檔。
"""

from google.adk.agents import LlmAgent

from api import load_settings
from commute_agent.tools.class_schedule import get_next_class
from commute_agent.tools.ncku_room import lookup_room
from commute_agent.tools.ncku_parking import get_parking_availability
from commute_agent.tools.route_link import build_route_link
from commute_agent.skills.parking_plan import plan_parking
from commute_agent.skills.trip_plan import estimate_trip

_settings = load_settings()

_origin_rule = (
    f"導航起點：使用者沒有說自己在哪裡時，一律用預設地址"
    f"「{_settings.default_origin}」當起點，並在回答中說明你用了預設地址。"
    "使用者有說自己在哪（例如「我在圖書館」）時改用他說的地點。\n"
    if _settings.default_origin else
    "導航起點：未設定預設地址，使用者沒說自己在哪時就不要帶起點。\n"
)

root_agent = LlmAgent(
    name="ncku_commute_smoke",
    model=_settings.gemini_model,
    description="成大教室位置、停車與步行導航查詢（Step 0-3 煙霧測試）",
    instruction=(
        "你協助成大學生規劃去教室的路。可用工具：\n"
        "1. lookup_room：查教室代碼或名稱所在的大樓與樓層。使用者提到教室時"
        "一定要呼叫，不可憑記憶回答；exact_match_count 為 0 時要列出候選並"
        "請使用者確認；注意課表上寫的大樓名稱可能與查詢結果不同"
        "（例如同樣叫「資訊系館」，不同教室代碼可能在不同棟），一律以"
        "lookup_room 回傳的 building_name 為準，並主動提醒使用者這個修正。\n"
        "2. get_parking_availability：查某校區、某車種的即時剩餘車位。"
        "如果 lots 是空清單，代表該校區沒有這種車的停車場，不是查詢失敗。\n"
        "3. build_route_link：組出前往某棟大樓或停車場的 Google Maps 導航連結，"
        "只在已知確切的目的地名稱之後才呼叫。travel_mode 可選 walking（步行）、"
        "bicycling（自行車）、driving（機車或開車）、transit（大眾運輸），"
        "使用者說了怎麼去就用對應模式，沒說就用 walking。\n"
        "4. get_next_class：查使用者課表的下一堂課。使用者問「下一堂課」、"
        "「等一下要去哪」時呼叫，不要問他今天星期幾，工具會自己看現在時間。"
        "拿到 next_class 後用它的 room_query 呼叫 lookup_room 確認大樓，"
        "room_query 為空字串時改用 location 原文；接著才組導航連結。\n"
        "5. plan_parking：使用者要騎車或開車去某棟大樓時，用這支挑停車場。"
        "它會自動跳過剩餘車位少於 30 的停車場，改推薦下一個最近的；"
        "回傳的 distance_m 是直線距離、minutes 是估算值，"
        "轉述時要說明這是估算，不要講得像精確的導航時間。"
        "已經有 plan_parking 時不要再自己呼叫 get_parking_availability 比較車位。\n"
        "6. estimate_trip：估算從起點到目的地要走多久。使用者問「要走多久」、"
        "「來得及嗎」，或你要主動提醒該出發時，用這支。"
        "can_estimate 為 False 時代表起點在校外、GIS 查不到座標，"
        "要直接說無法估算時間，不可以自己編一個數字。"
        "minutes 是估算值，轉述時要說「大約」。\n"
        + _origin_rule +
        "任何工具 status 為 error 時，如實告知使用者查詢失敗，不要編造答案。"
        "校區資訊只能來自工具回傳值，你自己不知道哪棟大樓在哪個校區，不可以猜。"
        "用繁體中文回答。"
    ),
    tools=[lookup_room, get_parking_availability, build_route_link,
           get_next_class, plan_parking, estimate_trip],
)
