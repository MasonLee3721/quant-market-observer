# M0 資料契約

版本：`schema-v0.1`

## 主鍵與型別

- 股票代碼一律使用字串，保留前導零。
- 日期使用 ISO 8601 `YYYY-MM-DD`，語意為台北交易日。
- 每張日資料表主鍵為 `(trade_date, stock_id)`；法人長表額外包含 `investor_type`。
- 金額以新台幣元、數量以股為標準單位；原始來源單位必須在轉換時記錄。

## 共通欄位

| 欄位 | 型別 | 說明 |
|---|---|---|
| `trade_date` | date | 交易日 |
| `stock_id` | string | 股票代碼 |
| `market` | enum | `TWSE`／`TPEx` |
| `source` | string | 資料來源與 dataset |
| `retrieved_at` | datetime | UTC 擷取時間 |
| `schema_version` | string | 標準化 schema 版本 |
| `quality_flags` | string[] | 缺值、異常、尚未定案等旗標 |

## 缺值政策

- `null`：來源缺值、尚未公布或無法計算。
- `0`：來源明確回傳零，且該欄位適用於此股票。
- 不適用：以 `null` 搭配 `not_applicable` 旗標。
- 暫停交易：價格與成交可缺值，搭配 `suspended` 旗標，不做前值填補。

## 價格政策

- 原始 OHLC 不自行還原。
- 報酬研究必須明確選擇未還原、還原或總報酬序列。
- 未完成除權息處理前，不以跨除權息的原始價格報酬作正式績效結論。

## 時間可得性

- 價量、法人與融資資料視為交易日收盤後才可得。
- 報表生成可使用 T 日資料；交易回測最早於 T+1 執行。
- 來源資料若事後修訂，保留擷取批次與 `retrieved_at` 以支援重現。

## 股票主檔與族群

- 股票主檔使用有效起訖日，不以今日名單回填整段歷史。
- 族群採多標籤模型；`config/universe_spike.csv` 是 spike 的單一主題簡化視圖。
- 正式表應包含 `stock_id, theme, subtheme, valid_from, valid_to, taxonomy_version, evidence`。
