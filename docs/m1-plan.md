# M1 執行計畫：資料管線 MVP

## 目標

將 M0 的可行性腳本轉換成可維護、可測試、可每日重跑的資料管線。M1 不計算投資訊號，也不產生最終 HTML；它只負責提供可信、可追溯的標準化資料。

## 架構邊界

```text
Provider → Raw Snapshot → Normalizer → Validator → Storage → CLI Status
```

### Provider

- `FinMindProvider`：歷史價量、法人、融資。
- `TwseProvider`：上市最新盤後資料與官方核對。
- `TpexProvider`：上櫃最新盤後資料與官方核對。
- 外部回應原樣保存，provider 不偷偷修正資料。

### Normalizer

- 統一股票代碼、交易日、欄位名稱與單位。
- 將無成交價格 0 轉為 `null`，加入 `no_trade`。
- 保留 `source`、`retrieved_at`、`schema_version`。
- 缺值、零值與不適用必須維持不同語意。

### Validator

- 主鍵唯一與 schema 檢查。
- 日期、價格、成交量及金額合理性。
- 股票覆蓋與資料新鮮度。
- 官方抽樣差異。
- 驗證失敗時阻止發布標準化資料。

### Storage

- Raw：不可變 JSON 快照。
- Normalized：Parquet。
- Catalog／quality：DuckDB。
- 以 batch ID 連結來源、標準化結果與品質報告。

### CLI

```bash
qmo update --date latest
qmo validate --batch <batch-id>
qmo status
```

## 工作包

### WP1 — 技術棧與專案骨架

- Python 3.12、`pyproject.toml`、lint、type check、pytest。
- `src/qmo/` 模組與 CLI 空殼。
- ADR：由 Node spike 過渡至 Python 的理由。

驗收：乾淨環境可以安裝，測試及靜態檢查通過。

### WP2 — Provider

- 共用 provider protocol、錯誤型別與重試政策。
- FinMind、TWSE、TPEx provider。
- timeout、rate limit、backoff、快取與 contract tests。

驗收：不連網測試可重播 fixture；端點 schema 變更會明確失敗。

### WP3 — Normalizer 與資料模型

- `DailyPrice`、`InstitutionalFlow`、`Margin`、`StockMaster` schema。
- M0 零值／缺值政策、單位與來源 metadata。
- Node spike 與 Python 結果對照測試。

驗收：50 檔 M0 資料可重建，核心筆數及品質結果一致。

### WP4 — Storage 與批次追蹤

- raw／normalized／catalog 目錄與命名規則。
- Parquet、DuckDB、batch manifest、hash 與錯誤紀錄。
- 原子發布與失敗保留上一版。

驗收：同一批次可重現；重跑不會產生不受控重複資料。

### WP5 — Validator

- schema、主鍵、覆蓋、新鮮度與合理範圍。
- TWSE／TPEx 價量、法人、融資抽樣對帳。
- JSON 與 Markdown 品質報告。

驗收：注入重複、缺值、零價、過期與來源差異時正確失敗。

### WP6 — CLI 與文件

- `update`、`validate`、`status`。
- 設定範例、環境變數、runbook 與故障排除。

驗收：新協作者只依 README 可完成 50 檔更新與驗證。

## 執行順序與依賴

```text
WP1
 ├─ WP2 ─┐
 └─ WP3 ─┼─ WP4 ─ WP6
         └─ WP5 ──┘
```

WP2 與 WP3 可平行進行；WP4 依賴正式資料模型；WP5 可先用 fixture 開發，最後接入 Storage；WP6 收斂所有流程。

## Definition of Done

- [ ] 單一指令更新 50 檔價量、法人及融資。
- [ ] TWSE、TPEx、FinMind provider 可替換且有 contract tests。
- [ ] Raw snapshot 不可變，normalized 可由 raw 重建。
- [ ] schema、單位、來源與批次資訊完整。
- [ ] 缺值、零值、無成交與未更新可區分。
- [ ] 品質失敗阻止發布，且不覆蓋上一批成功資料。
- [ ] 50 檔 M0 回歸測試通過。
- [ ] 官方價量抽樣對帳通過；法人／融資對帳有明確結果。
- [ ] 公開 repo 不含 token 或大量原始資料。
- [ ] README、runbook 與協作文件同步更新。

## 不屬於 M1

- 市場分數、族群分數、個股排名。
- 策略回測與持倉。
- HTML 儀表板。
- ETF 被動流量。
- 自動下單。
