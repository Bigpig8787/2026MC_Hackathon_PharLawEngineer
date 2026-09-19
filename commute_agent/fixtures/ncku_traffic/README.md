# ⚠️ 這個資料夾跟 `fixtures/README.md` 的規則不一樣

`Tainan.json` 不是真實 API 回應的錄製，是**手寫的示範資料**。

原因：`get_road_events`（`commute_agent/tools/road_events.py`）呼叫的 TDX
路況事件 API 需要 `TDX_CLIENT_ID` / `TDX_CLIENT_SECRET`（免費申請，
https://tdx.transportdata.tw 會員中心），這個專案目前的 `.env` 還沒有這組金鑰，
所以沒辦法對真實端點打一次、錄下真正的回應格式。

`parse_road_events()` 是照 TDX 其他資料集常見的欄位命名（例如站牌座標
`Position.PositionLon/PositionLat`）寫的**推測解析**，不保證跟 RoadEvent
這個資料集的真實欄位完全一樣。

**拿到金鑰後該做的事：**

1. 把 `TDX_CLIENT_ID`、`TDX_CLIENT_SECRET` 填進根目錄 `.env`。
2. 執行 `python scripts/smoke_tdx_road_events.py`（`PROVIDER_MODE` 需為 `live`）。
3. 如果 `parse_road_events` 丟出 `SchemaError`，錯誤訊息會列出真實欄位名稱，
   照著改 `road_events.py` 裡的 `_ID_KEYS` / `_TYPE_KEYS` / `_ROAD_NAME_KEYS` /
   `_TIME_KEYS` / `_FLAT_LON_KEYS` / `_FLAT_LAT_KEYS` 候選清單即可。
4. 用 `--record` 把一次真實回應存成這個資料夾裡的檔案，取代這份手寫版，
   並在這份 README 補上錄製日期與來源（比照 `fixtures/README.md` 的格式）。
