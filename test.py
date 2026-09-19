from dotenv import load_dotenv
from google import genai

# 自動讀取當前資料夾的 .env 檔案
load_dotenv()

client = genai.Client()

response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents="請用一句話打招呼！",
)

print(response.text)