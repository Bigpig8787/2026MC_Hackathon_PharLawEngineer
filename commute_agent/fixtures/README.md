# Fixtures

這裡的檔案都是**真實 API 回應的原始錄製**，不是手寫的假資料。
`PROVIDER_MODE=fixture` 時，Tool 會讀這裡的檔案而不打網路。

| 檔案 | 來源 | 錄製日期 |
| --- | --- | --- |
| `ncku_gis/roominfo/4264.json` | `db.nckumap.ncku.edu.tw/nckugis/public/roominfo.htm?q=4264` | 2026-09-19 |
| `ncku_gis/roominfo/65304.json` | `db.nckumap.ncku.edu.tw/nckugis/public/roominfo.htm?q=65304` | 2026-09-19 |
| `ncku_parking/C_moto.html` | `apss.oga.ncku.edu.tw/park/index.php/park11215/read`（campus=C 自強, tab=moto 機車） | 2026-09-19 |
| `ncku_parking/G_moto.html` | 同上（campus=G 勝利, tab=moto）；真實回應為「查無符合條件之停車場資料」 | 2026-09-19 |

新增錄製：`python scripts/smoke_ncku_gis.py --record <查詢字>`

資料著作權屬國立成功大學（總務處資產保管組），僅供本專案開發測試使用，勿另行散布。
