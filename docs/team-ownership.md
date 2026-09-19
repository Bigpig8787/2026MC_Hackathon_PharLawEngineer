# 分工與交接

主線（A）已跑通：承諾 → 四模式規劃 → 劇本推進 → 自動改計畫 → 確認閘門 → 教室卡。全程 fixture，無 key 可 demo。

每個空殼 = 一個 class + `IMPLEMENTED = False` + docstring 寫清楚資料來源與回傳格式。接手者：
1. 讀 class docstring 與 `campuspulse/providers/base.py` 的 Protocol。
2. 實作 `fetch()` / `locate()` / `send()`，回傳同樣的 model。
3. 把 `IMPLEMENTED = True`。`PROVIDER_MODE=auto` 且 key 齊全時 registry 會自動選用。
4. 加 contract test：用 `httpx.MockTransport` 餵假回應，斷言 normalized 欄位與錯誤碼（範例：`tests/test_google_routes.py`）。
5. 不要改 planner；訊號格式在 `providers/registry.py` 註解與 `tests/test_planner.py` 的 `_signals()`。

| 人 | 資料夾 | 交付 | 驗收 |
|---|---|---|---|
| A | core、routing、scenario、ai/gemini、ai/rationale、web | 已完成主線 | `pytest -q` 全綠、`npm run build` 通過 |
| B | providers/weather/cwa.py、flood/wra.py、bike/tdx_youbike.py、transit/tdx_bus.py | 4 個 live adapter | `/api/health` 的 providers 顯示 `live`；contract test |
| C | ai/timetable.py、providers/email/gmail.py（讀信分類） | 課表圖 → commitments；教授信 → 重要度／教室變更 | fixture 圖 3 張（清晰／模糊／錯位）皆有輸出；低信心走人工修正 |
| D | data/ncku/*.json、providers/indoor/floorplan_gemini.py、providers/parking | 成大官網抓座標、入口、停車場；平面圖；教室卡 live | 每筆 `verified: true`；4263 導引由平面圖產生 |
| E | providers/calendar、email send、部署、demo | Calendar 預覽/寫入、真寄信（需確認）、Cloud Run／Vercel、簡報 | 兩次從重設跑完 demo 不出錯 |

## 本機啟動

後端（apps/api）：
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn campuspulse.main:app --reload --port 8000
pytest -q
```

前端（apps/web）：
```powershell
npm install
npm run dev
```

## 規則

- `main` 隨時可 demo；功能分支 + PR（見 CONTRIBUTING.md）。
- key 只放 `apps/api/.env`；不進 git、不進截圖、不進聊天。
- UI 上每個訊號都要有來源徽章；fixture 不可偽裝 live。
- 外部寫入（信、行事曆）預設 dry-run；真寫入只在使用者按確認後。
