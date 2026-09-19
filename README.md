# NCKU Smart Commute（成大智慧通勤 Agent）

## 架構

- **Application 層**：`commute_agent/agent.py`（目前為 Step 0 煙霧測試版）
- **Skill 層**：`commute_agent/skills/`（Step 4 加入）
- **Tool 層**：`commute_agent/tools/`，只打 API、不做決策
- **設定**：`api.py`，只讀環境變數，不含任何金鑰

## 安裝（Windows PowerShell）

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # .env 放在專案根目錄，跟 api.py 同一層
```

打開 `.env`，填入 `GEMINI_API_KEY`。

**執行 `adk web` 請用獨立的 PowerShell 視窗**（不要用 VS Code 內建終端機），
VS Code 的 Python 擴充功能可能會干擾長時間執行的伺服器程序。

## 驗證

```powershell
python -m pytest -q                              # 單元測試，不需網路與金鑰（目前 47 項）
python scripts/smoke_ncku_gis.py 4264 65304 格致廳   # 打真實成大教室 GIS
adk web                                          # 開 http://localhost:8000
```

在 `adk web` 問「4264 教室在哪？」，左側 Events/Trace 應看到 `lookup_room` 的真實呼叫。
要打真實 API，把 `.env` 的 `PROVIDER_MODE` 改成 `live`。

## 目前已完成的 Tool

| Tool | 檔案 | 說明 |
| --- | --- | --- |
| `lookup_room` | `tools/ncku_room.py` | 教室代碼／名稱 → 大樓與樓層 |
| `get_parking_availability` | `tools/ncku_parking.py` | 校區＋車種 → 即時剩餘車位（依車位數排序） |
| `build_route_link` | `tools/route_link.py` | 目的地 → Google Maps 導航連結，可選步行／自行車／機車開車／大眾運輸（純函式，不需金鑰） |
| `get_next_class` | `tools/class_schedule.py` | 讀 `data/class_schedule.json`，依現在時間算出正在上的課與下一堂 |
| `get_building_location` | `tools/ncku_geo.py` | 大樓名稱 → 經緯度，另含距離與時間估算的純函式 |
| `plan_parking` | `skills/parking_plan.py` | 目的地大樓＋車種 → 最近且車位足夠的停車場（Skill 層，會串多個 Tool） |
| `estimate_trip` | `skills/trip_plan.py` | 起點＋目的地 → 距離與估算時間，起點在校外時明確回報無法估算 |

## 課表視覺化頁面

```powershell
./.venv/bin/python -m web.server     # http://localhost:8080
```

顯示本週課表、下一堂課與導航連結，可切換交通模式；選「機車／開車」時會
自動比對全校停車場，推薦最近且剩餘車位 ≥ 30 的那一個。

出發地可以在頁面上自己填（例如「成大圖書館」），留空則用 `.env` 的
`DEFAULT_ORIGIN`。填校內地點時會顯示估算的距離與時間；校外地址算不出來，
頁面會直接說明原因而不是給一個假數字。

## 已知的資料限制

- **時間是估算值**：直線距離乘 1.3 繞路係數再除以平均速度，不含紅綠燈與實際路網。
  要精確時間得接 Google Maps Routes API（需金鑰與計費）。
- **只有校內起點算得出時間**：距離來自成大 GIS 的大樓座標，所以起點與目的地
  都必須是校內地點。校外地址（例如住家、火車站）GIS 查不到，`estimate_trip`
  會回 `can_estimate=False`，不會拿附近大樓的座標充數。要支援校外起點得接
  地理編碼服務。
- **6 個停車場沒有座標**：校門（光復前門、成功前門、勝利後門）、路名（林森路）
  與成杏校區兩個停車場在 GIS 查不到同名大樓，不會被硬填座標，排序時排最後。
  重建對照表：`./.venv/bin/python scripts/build_parking_locations.py`
- **兩套校區代碼不相通**：GIS 的 `campusId` 是大樓編號前綴（A104 → A），
  與停車系統的 `CAMPUS_CODES`（A=光復、B=成功…）不是同一套，不可互相套用。

## 尚未完成

- 室內樓層平面圖（`buildinfo.htm?action=getBoundByBuildId` 等，資料格式待確認）
- 課表截圖辨識
- Skill 層目前只有 `parking_plan`，尚未改用 ADK 的 `SkillToolset` 與自我修正 loop

## 團隊規範

分支、commit 與 PR 規範沿用 CampusPulse 的 CONTRIBUTING.md。
Gemini key 只能在後端使用；不要透過截圖、聊天或 PR 傳遞任何金鑰。
