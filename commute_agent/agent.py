"""Step 0 煙霧測試用的最小 Agent。

目的只有一個：確認 ADK + Gemini + 真實 Tool 呼叫整條線能通。
Step 5 會以正式的 Application 層（主 Agent + SkillToolset）取代本檔。
"""

from google.adk.agents import LlmAgent

from api import load_settings
from commute_agent.tools.ncku_room import lookup_room
from commute_agent.tools.ncku_parking import get_parking_availability
from commute_agent.tools.walking_link import build_walking_link

_settings = load_settings()

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
        "3. build_walking_link：組出前往某棟大樓的 Google Maps 步行導航連結，"
        "只在已知確切的 building_name 之後才呼叫。\n"
        "任何工具 status 為 error 時，如實告知使用者查詢失敗，不要編造答案。"
        "用繁體中文回答。"
    ),
    tools=[lookup_room, get_parking_availability, build_walking_link],
)
