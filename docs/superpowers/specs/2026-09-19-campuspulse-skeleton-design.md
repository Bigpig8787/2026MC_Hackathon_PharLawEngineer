# CampusPulse 骨架與導航主線設計

日期：2026-09-19
狀態：已審閱，plan 見 docs/superpowers/plans/2026-09-19-campuspulse-skeleton.md

## 目標

建立五人可平行開發的專案骨架，並讓「導航主線」跑得起來：

1. 承諾（課表上的一堂課）→ 四種交通方式全算 → 推薦一個 → 每種方式含「最後一個決定」。
2. 劇本時鐘推進 → 訊號改變 → 計畫自動改 → 時間軸與決策計數器可見。
3. 無任何 API key 時全程用 fixture 可 demo；填 key 後 routing 自動切 live，UI 標示 `live` / `fixture`。
4. 其他功能為空殼：一個介面 + fixture 實作 + `TODO(live)`，接手者只填 live。

### 非目標（本輪不做）

課表 OCR 的 live 實作、Gmail/Calendar 真讀寫、氣象／積淹水／TDX live adapter、平面圖多模態辨識、真鬧鐘、真寄信、部署。

## 產品原則（planner 與 UI 都要守）

- **省專注力**：使用者從頭到尾不輸入目的地。成功指標＝決定數 7→0、開 app 數 5→0、最多 1 次確認。
- **主動**：計畫由系統產生並持續監控；改變由 trigger 觸發，不是使用者重問。
- **最後一個決定**：機車→停哪場、YouBike→還哪站、公車→哪站下、步行→哪個門。
- **可解釋**：每個計畫附選誰、拒誰、決定性訊號、時間戳、來源模式、下次檢查時間。
- **誠實**：不保證準時；缺資料標 `unavailable`；外部寫入預設 dry-run 且需確認。

## 技術棧

| 層 | 選擇 | 理由 |
|---|---|---|
| 後端 | Python 3.12、FastAPI、Pydantic v2、httpx、pytest | 團隊選擇；planner 純函式好測 |
| 前端 | React 18、Vite、TypeScript、Tailwind、react-leaflet | Leaflet + OSM 圖磚免 key，五人開箱即跑 |
| 路線 | Google Routes API `computeRoutes`（WALK / DRIVE / BICYCLE / TRANSIT） | 唯一單一 API 覆蓋四模式含台南公車 |
| 模型 | `google-genai` SDK；Flash 產生說明文字；Pro 保留給衝突訊號仲裁（本輪不接） | 無 key 時用模板文字 |
| 秘密 | 只在 `apps/api/.env`；前端經 Vite proxy 呼叫後端 | 符合 CONTRIBUTING |

機車：Routes API 台灣可能無 `TWO_WHEELER`，以 `DRIVE` 代替並在 evidence 標註 `mode_proxy: DRIVE`。實作時驗證。

## Repo 佈局

```
apps/
  api/                       FastAPI
    campuspulse/
      main.py                app、CORS、路由掛載
      settings.py            env 讀取、provider mode
      core/
        models.py            Commitment, Signal, TravelOption, LastDecision, Plan, DecisionRecord, Trigger, ProposedAction
        planner.py           純函式：(commitment, origin, routes, signals, campus) -> Plan
        triggers.py          純函式：(old_plan, new_plan, signals) -> list[Trigger]
        loop.py              perceive → plan → act → reflect；維護 timeline 與 decision count
      providers/
        base.py              Protocol 介面 + SourceMode enum + ProviderError
        routing/             google_routes.py（live）、fixture.py
        weather/             fixture.py、cwa.py（空殼）
        flood/               fixture.py、wra.py（空殼）
        bike/                fixture.py、tdx_youbike.py（空殼）
        transit/             fixture.py、tdx_bus.py（空殼）
        parking/             fixture.py（校方資料未知，先永遠 fixture）
        indoor/              fixture.py、floorplan_gemini.py（空殼）
        email/               fixture.py、gmail.py（空殼）
        calendar/            fixture.py、google_calendar.py（空殼）
        registry.py          依 settings 組裝 live 或 fixture
      ai/
        gemini.py            client、JSON schema 驗證、無 key 時回 None
        rationale.py         DecisionRecord -> 兩句中文說明（模板 fallback）
        timetable.py         課表圖 -> Commitment[]（空殼，回 fixture）
      scenario/
        runner.py            fixture 時鐘：reset / step / inject
      api/
        routes_state.py      GET /api/state
        routes_scenario.py   POST /api/scenario/reset|step|inject
        routes_actions.py    POST /api/actions/{id}/confirm|reject
        routes_plan.py       POST /api/plan（直接呼叫 planner，供其他人測）
    data/ncku/
      buildings.json         id、名稱、校區、經緯度、入口[{name, lat, lng}]
      parking_lots.json      id、名稱、經緯度、covered、capacity
      rooms.json             room -> building_id、floor、wing、instructions
    fixtures/
      scenarios/ncku-wed-0900.json   劇本時間軸
      routes/                  四模式預算好的路線 JSON
    tests/
      test_planner.py
      test_triggers.py
      test_scenario.py
    requirements.txt
    .env.example
  web/                       React + Vite
    src/
      api/client.ts          fetch /api/*
      types.ts               與後端 models 對應（手寫，不生成）
      App.tsx
      components/
        CommitmentCard.tsx   哪堂課、幾點、哪間、重要度
        PlanCard.tsx         四模式 tab；推薦／可行／不可行＋原因；最後一個決定
        MapView.tsx          Leaflet；路線 polyline；起點、最後決定點、入口
        Timeline.tsx         感知／規劃／行動／反思事件
        ScenarioBar.tsx      時鐘、推進、注入、provider 徽章
        DecisionCounter.tsx  「已幫你做 N 個決定，你做了 M 個」
        ActionModal.tsx      信件預覽、確認／拒絕
        IndoorCard.tsx       到樓下時出現：樓層、翼、樓梯
    vite.config.ts           proxy /api -> http://localhost:8000
docs/
  team-ownership.md          資料夾 → 負責人 → 交付 → 驗收
  api-and-data.md            key 怎麼拿、env 名稱、手工資料清單
  superpowers/specs/         本文件
```

根目錄 `api.py` 保留不動；主線不用它。

## 核心型別（Pydantic）

```
Mode = walk | scooter | bike | transit
SourceMode = live | fixture | stale | unavailable
Importance = normal | high | critical

Commitment: id, title, start (datetime, Asia/Taipei), building_id, room, importance, source, confirmed
Signal: kind (rain|flood|bike|transit|parking), observed_at, valid_until, value (dict), source_mode, confidence
RouteResult: mode, duration_min, distance_m, polyline [[lat,lng]], summary, corridor_ids, source_mode, mode_proxy?
LastDecision: kind (parking_lot|bike_dock|bus_stop|gate), target_id, label, walk_min, reason
TravelOption: mode, route, last_decision?, base_eta_min, conservative_eta_min, depart_at, arrive_at, feasible（到達 ≤ start − buffer）, on_time（到達 ≤ start）, slack_min, reasons [str], risk_flags [str], reliability (0-1), score, evidence [str]
Plan: commitment_id, generated_at, selected: TravelOption?, options [TravelOption]（四模式排序後全列，含 selected）, rationale, next_check_at, status (ok|late_risk|no_feasible|arrived), decisions_made
Trigger: kind, description, old, new, observed_at, material (bool)
ProposedAction: id, type (email|calendar), preview {to, subject, body} | {event}, state (proposed|confirmed|rejected|executed_dry_run), created_at
DecisionRecord: plan, triggers, rejected [{mode, reasons}], signals_used, policy_version, model_id?
TimelineEvent: at, phase (perceive|plan|act|reflect), title, detail, source_modes
```

## Planner 規則（deterministic，policy_version = "0.1"）

**緩衝**：normal 5 分、high 10 分、critical 15 分。

**天氣係數**（rain_mm_h 為目前或下一小時預報較大者）：

| 雨量 | walk | bike | scooter | transit |
|---|---|---|---|---|
| < 5 | 1.0 | 1.0 | 1.0 | 1.0 |
| 5–20 | 1.3 | 1.4 | 1.2 | 1.05 |
| ≥ 20 | 1.6 | 不可行（unsafe_heavy_rain） | 1.3 | 1.1 |

**積淹水**：flood signal 含 `corridor_ids`；若路線 `corridor_ids` 命中且 level ≥ warning → walk/bike/scooter 該路線不可行（flood_on_route）。若 routing 提供替代路線（fixture 有）則改用替代路線並加 `rerouted` 標記。

**YouBike**：起點站 available = 0 → 不可行（no_bike）。終點站 docks = 0 → 最後決定改成下一個有位的站，步行時間加到 ETA。

**公車**：depart_at = 下一班到站時間（transit signal `next_eta_min`）；ETA 來自 routing TRANSIT。next_eta_min 缺 → 標 `unavailable`，reliability 降 0.3。

**機車停車**：候選停車場 free > 0；雨量 ≥ 5 優先 covered；其餘依到入口步行時間；選定的 walk_min 加到 ETA。全滿 → 不可行（no_parking）。

**模式固定成本**：scooter +3（戴帽、停車）、bike +2（借車）、walk +0、transit +2（上下車）。

**conservative_eta = duration × 係數 + 固定成本 + last_decision.walk_min**。
**arrive_at = depart_at + conservative_eta；feasible = arrive_at ≤ start − buffer**（且無不可行標記）。

**depart_at**：walk/bike/scooter 取「最晚可出門」＝ start − buffer − conservative_eta（但不早於 now）；transit 取下一班。

**reliability**（基準）：transit 0.8、scooter 0.7、walk 0.9、bike 0.6；雨 ≥ 5 時 bike −0.2、walk −0.1；雨 ≥ 20 時 scooter −0.1；資料 stale −0.2；unavailable −0.3。

**排名**：feasible 優先；importance ≥ high 時 reliability 權重 0.7、時間 0.3；normal 時反之。分數相同取 conservative_eta 小者。無可行 → status = no_feasible，selected = None，rationale 說明並提出最小傷害動作。

**排序層級**：feasible → on_time（緩衝被吃掉但仍準時）→ 其他。**late_risk**：selected 只有 on_time 而非 feasible；**no_feasible**：無人 on_time。兩者在 user_state = home 時產生 email ProposedAction（預覽助教＋組員），同類 pending 只建一次。

## Trigger 規則（material 才重新通知）

- 任一模式 feasible 翻轉。
- selected 模式改變。
- selected 的 depart_at 提早 > 3 分或 ETA 增加 > 5 分。
- selected 路線出現 flood。
- selected 為 bike 且 available 降為 0；selected 為 scooter 且停車場 free 降為 0。
- Cooldown：同類 trigger 5 分鐘內不重複，feasible 翻轉除外。

## Loop 與劇本

`ScenarioRunner` 持有 fixture 時鐘。每步：
1. **perceive**：讀該時刻 signals（fixture 或 live，各自標 source_mode）與 user_state。
2. **plan**：呼叫 planner；比對舊計畫產生 triggers。
3. **act**：計畫變且 material → 更新 selected、寫 timeline、decision_count += 決定數（每模式可行性 1、選擇 1、每個 last_decision 1、每個 trigger 1）；late_risk → 建 ProposedAction。
4. **reflect**：寫 next_check_at；user_state = arrived_building → 附 IndoorCard 資料。

劇本 `ncku-wed-0900.json`：

| 步 | 時刻 | 注入 | 期望 |
|---|---|---|---|
| 0 | 07:50 | 雨 0、YouBike 8/5、公車 6 分、停車場 A 12/B 30/C 5、無積水 | 推薦機車，停 A（露天、最近） |
| 1 | 08:15 | 雨 25、小東路積淹水 warning、YouBike 0、公車 4 分 | bike 不可行；機車改替代路線停 B（遮雨）；或 transit 勝出——由 planner 決定，測試鎖定結果 |
| 2 | 08:27 | user_state = home | late_risk；email 預覽 |
| 3 | 08:50 | user_state = arrived_building | IndoorCard：4263 → 4F 東側，東側門進，右手邊樓梯 |

起點（fixture）：東區租屋 22.9905, 120.2280。目的：資訊系館 22.9997, 120.2220（近似值，D 校正）。

## API

| Method | Path | 作用 |
|---|---|---|
| GET | /api/health | provider 模式、缺哪些 key（不含值） |
| GET | /api/state | commitment、plan、alternatives、signals、timeline、decision counts、proposed actions、indoor card、clock |
| POST | /api/scenario/reset | 回到步 0 |
| POST | /api/scenario/step | 前進一步 |
| POST | /api/scenario/inject | body: 部分 signals 覆寫，立即重跑 loop |
| POST | /api/actions/{id}/confirm | dry-run 執行，state = executed_dry_run |
| POST | /api/actions/{id}/reject | |
| POST | /api/plan | body: commitment + origin + signals → Plan（給其他人單測 planner） |

狀態存在記憶體（單使用者 PoC）；重啟即 reset。

## UI（手機寬單欄，桌機置中 480px）

由上到下：ScenarioBar（時鐘、推進、重設、provider 徽章）→ CommitmentCard → PlanCard（四 tab，推薦者預設；每 tab：出門、到達、最後決定、可行／不可行原因、來源時間戳）→ MapView → DecisionCounter → Timeline → IndoorCard（到樓下才出現）。ActionModal 在 late_risk 時彈出。

## 測試

- `test_planner.py`：基準可行；bike=0 不可行；雨 25 bike 不可行；flood 使路線不可行且替代路線 rerouted；high importance 偏 reliability；停車場全滿 no_parking；無可行 → no_feasible。
- `test_triggers.py`：feasible 翻轉為 material；ETA +2 分非 material；cooldown。
- `test_scenario.py`：步 0→1 selected 改變且 timeline 含 perceive/plan/act/reflect；步 2 產生 email action；confirm 不真寄。
- 全部無網路。

## 環境變數（apps/api/.env.example）

```
PROVIDER_MODE=fixture        # fixture | auto（有 key 的 provider 走 live）
DRY_RUN=true
TIMEZONE=Asia/Taipei
GEMINI_API_KEY=
GEMINI_FLASH_MODEL=gemini-3-flash-preview
GEMINI_PRO_MODEL=gemini-3-pro-preview
GOOGLE_MAPS_API_KEY=         # Routes API
TDX_CLIENT_ID=
TDX_CLIENT_SECRET=
CWA_API_KEY=
WRA_API_KEY=
```

## 分工

| 人 | 資料夾 | 交付 |
|---|---|---|
| A | core、routing、ai/gemini、ai/rationale、scenario、web 主線 | 本輪 |
| B | providers/weather、flood、bike、transit live | 4 個 adapter + contract test |
| C | ai/timetable、providers/email | 課表 OCR、教授信分類 |
| D | data/ncku、providers/parking、providers/indoor | 從成大官網（校園地圖、總務處、系網）抓建築座標、入口、停車場、平面圖，取代本輪 fixture 近似值；平面圖、IndoorCard live |
| E | providers/calendar、ActionModal 真寄信、部署、demo 腳本 | 確認閘門、Vercel/Cloud Run、簡報 |

## 待驗證（實作中確認）

1. Routes API 在台灣：`BICYCLE` 是否回路線；`TWO_WHEELER` 是否可用；`TRANSIT` 台南公車是否回站點。（A）
2. 資訊系館與租屋處座標 → D 從成大校園地圖校正；本輪 fixture 用近似值並在 JSON 標 `"verified": false`。
3. 成大機車停車場是否有即時資料 → D 查總務處；沒有就永遠 fixture，UI 標 `fixture`。

## data/ncku 資料來源（D）

- 建築名稱、校區、座標、入口：成大校園地圖。
- 停車場位置、有無遮雨、容量：總務處事務組／校園地圖。
- 教室編號規則、樓層平面圖：各系網（先做資訊系館）；找不到就拍門口逃生圖。
- JSON schema 由 A 本輪定，D 只換內容不改欄位。
