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
python -m pytest -q                              # 單元測試，不需網路與金鑰（目前 182 項）
python scripts/smoke_ncku_gis.py 4264 65304 格致廳   # 打真實成大教室 GIS
python scripts/smoke_tdx_road_events.py           # 打真實 TDX 路況事件（需 TDX_CLIENT_ID/SECRET）
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
| `get_road_events` | `tools/road_events.py` | 座標＋半徑 → 周邊 TDX 即時路況事件（車禍、施工、封閉），需 `TDX_CLIENT_ID`/`TDX_CLIENT_SECRET` |
| `check_route_events` | `skills/road_watch.py` | 起點＋目的地 → 各自周邊有沒有路況事件（Skill 層，串 `resolve_place` 與 `get_road_events`） |
| `estimate_trip` | `skills/trip_plan.py` | 起點＋目的地 → 距離與時間，並標明來源是估算還是實際路線 |
| `plan_ride_and_walk` | `skills/trip_plan.py` | 騎車行程拆成「騎到停車場」＋「走到教室」兩段，整趟只呼叫一次 Google |
| `get_travel_time` | `tools/travel_time.py` | 時間來源的統一接口，依設定選 `estimate` 或 Google Routes，後者失敗會自動退回前者 |
| `compute_route` | `tools/google_routes.py` | Google Routes API，真實路線時間（需金鑰、會計費） |
| `plan_departure` | `skills/departure_plan.py` | 倒推「該幾點出發」，含進教室緩衝；考試與報告自動加長緩衝 |
| `get_bike_status` | `tools/youbike.py` | 某地點附近 YouBike 可借車輛或可還空位（免金鑰） |
| `get_weather` | `tools/weather.py` | 中央氣象署臺南市鄉鎮預報，降雨機率與體感溫度（需 `CWA_API_KEY`） |
| `get_bus_eta` | `tools/tdx_bus.py` | TDX 臺南市公車即時到站（需 `TDX_CLIENT_ID`／`SECRET`） |

### 騎車行程為什麼要拆兩段

Google 只會算到大樓門口的騎車時間，但實際上得先停車再走過去。
`plan_ride_and_walk` 因此把行程拆開：

| 路段 | 來源 | 花錢 |
| --- | --- | --- |
| 出發地 → 停車場 | Google Routes API（真實路網） | 是，整趟一次 |
| 停車場 → 教室 | 成大 GIS 座標估算 | 否 |

送給 Google 的是**座標**而不是名稱——校內大樓帶編號前綴（`B406 三系館鋼構區`）
時 Google 常對到隔壁棟，實測就曾被解析成材料系館。座標由免費的 GIS 提供。

騎車段會明確指定走 Google，不受 `TRAVEL_TIME_PROVIDER` 影響——那段本來就是
付費才有意義的部分。走路與自行車則交給預設的 `auto` 自行判斷要不要花錢。

## 課表視覺化頁面

```powershell
./.venv/bin/python -m web.server     # http://localhost:8080
```

顯示本週課表、下一堂課與導航連結，可切換交通模式；選「機車／開車」時會
自動比對全校停車場，推薦最近且剩餘車位 ≥ 30 的那一個。

出發地可以在頁面上自己填（例如「成大圖書館」），留空則用 `.env` 的
`DEFAULT_ORIGIN`。校內地點用免費估算，校外地址（住家、車站）會自動改用
Google 的實際路線，介面會標明這次的時間是估算還是實際路線。

## 已知的資料限制

- **時間有兩個來源**，由 `.env` 的 `TRAVEL_TIME_PROVIDER` 決定策略：
  - `auto`（預設，建議）：免費的先試，答不出來才花一次 Google。校內兩點走路
    騎車不計費，只有校外起點與大眾運輸這種免費算不出來的情況才付費。
  - `estimate`：直線距離乘 1.3 繞路係數再除以平均速度。免費、免金鑰，
    但只涵蓋校內地點，而且偏樂觀（圖書館→資訊系館估 4 分，實際路線是 6 分）。
  - `google`：Google Routes API，真實路網與大眾運輸班次，起訖點可以是任意地址，
    因此校外住家也算得出來。需要 `GOOGLE_MAPS_API_KEY` 且**會計費**。
    金鑰缺失或 API 失敗時會自動退回 `estimate`，並在 `fallback_reason` 說明原因

  上層一律呼叫 `tools/travel_time.py` 的 `get_travel_time`，不必知道來源是哪個；
  回傳的 `is_estimate` 用來決定介面要不要寫「約」。
- **`estimate` 來源只算得出校內起點**：距離來自成大 GIS 的大樓座標，校外地址
  （住家、火車站）查不到。預設的 `auto` 會在這種情況自動改用 Google，
  所以校外起點仍算得出來；硬設成 `estimate` 才會回 `can_estimate=False`。
  任何情況下都不會拿附近大樓的座標充數。
- **6 個停車場沒有座標**：校門（光復前門、成功前門、勝利後門）、路名（林森路）
  與成杏校區兩個停車場在 GIS 查不到同名大樓，不會被硬填座標，排序時排最後。
  重建對照表：`./.venv/bin/python scripts/build_parking_locations.py`
- **兩套校區代碼不相通**：GIS 的 `campusId` 是大樓編號前綴（A104 → A），
  與停車系統的 `CAMPUS_CODES`（A=光復、B=成功…）不是同一套，不可互相套用。
- **路況事件是即時 feed，fixture 只是某一刻的快照**：`parse_road_events`
  （`tools/road_events.py`）已對真實 TDX 端點驗證過（2026-09-19），欄位命名
  不是猜的；但事件內容本身一直在變，`fixtures/ncku_traffic/Tainan.json`
  錄製當下成大周邊 500m 內剛好沒有事件，這是真實結果不是抓錯半徑，細節見
  `fixtures/ncku_traffic/README.md`。事件的分類代碼（`type_code`）沒有官方
  對照表，只在連 `description`／`category` 都沒有時才會是 `type_is_code=True`
  （目前實測沒遇過），這種情況不要自己編一個中文分類名稱。

## 對照 CampusPulse 規劃的進度

`CampusPulse.md` 描述的 Agent Loop 是 Perception → Planning → Action → Reflection。
目前完成到 Planning，Action 只做到「產生導航連結」，Reflection 尚未開始。

| CampusPulse 規劃的 Function | 狀態 | 備註 |
| --- | --- | --- |
| 課表理解 | 完成（JSON） | 截圖辨識尚未做，目前靠手動維護 `data/class_schedule.json` |
| 路線與時間 | 完成 | `estimate_trip`、`plan_ride_and_walk` |
| 出發時間推算 | 完成 | `plan_departure` |
| `get_bike_status()` | 完成 | YouBike 2.0 官方端點，免金鑰 |
| `get_weather()` | 完成 | 資料集 `F-D0047-077`（臺南市鄉鎮），不是縣市層級的 `-089` |
| `get_bus_eta()` | 完成 | 到站端點不支援 `nearby`，改以站牌 UID 過濾 |
| `get_flood_sensors()` | 未做 | 水利署，需註冊 |
| `get_air_quality()` | 未做 | 環境部，需註冊 |
| `read_course_email()`／`send_email()` | 未做 | Gmail API，需 OAuth |
| `update_schedule()` | 未做 | Google Calendar API，需 OAuth |
| 天氣影響出發建議 | 完成 | `plan_departure` 會看出發當下的降雨機率，騎車淋雨時建議改公車 |
| 持續監控與自動重新規畫 | 未做 | 目前都是使用者主動詢問才執行，還不會自己盯著環境變化 |

## 尚未完成

- 室內樓層平面圖（`buildinfo.htm?action=getBoundByBuildId` 等，資料格式待確認）
- 課表截圖辨識
- 尚未改用 ADK 的 `SkillToolset` 與自我修正 loop

## 團隊規範

分支、commit 與 PR 規範沿用 CampusPulse 的 CONTRIBUTING.md。
Gemini key 只能在後端使用；不要透過截圖、聊天或 PR 傳遞任何金鑰。
