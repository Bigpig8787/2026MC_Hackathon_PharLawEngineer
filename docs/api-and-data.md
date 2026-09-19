# 需要的 API、Key 與資料

## Key（全部免費）

| 用途 | 哪裡拿 | env 名稱 | 負責 |
|---|---|---|---|
| Gemini 3 Flash / Pro | Google AI Studio → Create API Key | `GEMINI_API_KEY` | 已有 |
| Google Routes API（步行／機車以 DRIVE 代／單車／公車） | GCP 專案 → 啟用 **Routes API** → 建 API key（限制只允許 Routes API）。用團隊 GCP 抵免額 | `GOOGLE_MAPS_API_KEY` | A |
| TDX（YouBike、公車到站） | https://tdx.transportdata.tw 註冊 → 會員中心 → API 金鑰 | `TDX_CLIENT_ID`、`TDX_CLIENT_SECRET` | B |
| 中央氣象署 | https://opendata.cwa.gov.tw 註冊 → 取得授權碼 | `CWA_API_KEY` | B |
| 水利署水資源物聯網 | https://iot.wra.gov.tw 申請 | `WRA_API_KEY` | B |
| Gmail / Calendar | GCP 同專案 → OAuth 同意畫面 → 桌面／Web 用戶端；scope 最小化 | 由 E 決定 env 名稱後加入 `.env.example` | E |

啟用方式：`apps/api/.env` 設 `PROVIDER_MODE=auto`。有 key 且 class `IMPLEMENTED=True` 的 provider 走 live，其餘 fixture。`GET /api/health` 看目前各 provider 模式。

## Routes API 注意

- 機車：台灣沒有 `TWO_WHEELER`，用 `DRIVE` + 避開高速公路代替，UI 標「以 DRIVE 代算」。
- `BICYCLE` 台灣覆蓋需實測；失敗會回 `unavailable`，planner 標該模式不可行並註明「無路線資料」。
- `TRANSIT` 台南公車 Google 有資料；需 `departureTime` 在未來，fixture 時鐘在過去時會略過此欄。
- 每次 `/api/state` 重算四模式 = 4 次呼叫；demo 前確認額度。

## 手工資料（D，從成大官網抓）

檔案都在 `apps/api/data/ncku/`，只改值不改欄位，改完把 `verified` 設 `true`。

| 檔案 | 內容 | 來源 |
|---|---|---|
| `buildings.json` | 建築 id、名稱、校區、座標、入口（哪側門、座標） | 成大校園地圖 |
| `parking_lots.json` | 機車停車場座標、有無遮雨、容量 | 總務處事務組／校園地圖 |
| `rooms.json` | 教室 → 建築、樓層、翼、入口、走法 | 系網平面圖；沒有就拍門口逃生圖 |
| `bike_stations.json` | 校園周邊 YouBike 站 | TDX 站點清單（B 提供 StationUID） |
| `bus_stops.json` | 校園周邊公車站 | TDX 站點清單 |
| `corridors.json` | 路名 → 走廊 id（積淹水對應用） | 自行維護 |
| `floorplans/<building>/<floor>.png` | 平面圖影像（新資料夾） | 系網 PDF 轉圖／逃生圖照片 |

先做資訊系館 + 2 棟常用系館；每棟至少 1 張平面圖。

## 待查（D）

- 成大教室編號規則（4263 = 哪棟幾樓？）→ 決定 IndoorCard 文案。
- 校內機車停車場有無即時車位（總務處）→ 沒有就永遠 fixture。
