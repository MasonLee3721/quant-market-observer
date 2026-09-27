# Project Status

最後更新：2026-09-27  
目前階段：**M1 — 資料管線 MVP（準備開始）**

## 一句話狀態

M0 已完成：50 檔、23 個代表主題、最近兩年的價量／法人／融資資料端到端驗證通過；下一步是把實驗腳本重構成可每日穩定執行的正式資料管線。

## 里程碑

| 里程碑 | 狀態 | 主要成果 |
|---|---|---|
| M0 研究規格與資料可行性 | ✅ 完成 | 資料契約、指標字典、50 檔 spike、官方抽樣對帳 |
| M1 資料管線 MVP | 🔜 下一步 | Provider、Normalizer、Validator、Storage、CLI |
| M2 訊號與排名 MVP | ⏳ 未開始 | 市場狀態、族群輪動、個股排名 |
| M3 回測與研究驗證 | ⏳ 未開始 | 成本、樣本外、Walk-forward、風險報告 |
| M4 HTML 報告 | ⏳ 未開始 | 響應式單一 HTML |
| M5 自動化與營運 | ⏳ 未開始 | 排程、監控、歷史快照、runbook |

## 已驗證事實

- 價量、法人與融資三個 dataset 均覆蓋 50/50 檔。
- 價量資料 24,193 筆，主鍵重複為 0。
- 三表同日完整 join 比率為 99.58%。
- 3 筆無成交資料已轉為 `null` 並標記 `no_trade`。
- TWSE 2330 與 TPEx 8069 的 OHLC、成交股數與成交金額完全一致。
- FinLab 不是必要依賴；TWSE／TPEx 為權威來源，FinMind 為歷史整合層。

## 當前優先順序

1. 決定 M1 正式執行環境與依賴管理方式。
2. 建立 provider／normalizer／validator／storage 邊界。
3. 將 TWSE、TPEx、FinMind 接口正式模組化。
4. 建立原始快照、標準化資料及品質紀錄。
5. 提供 `update`、`validate`、`status` 三個 CLI 指令。
6. 對法人與融資補上官方抽樣對帳。

## 協作者從哪裡開始

1. 閱讀 [README](README.md) 與 [完整專案計畫](PROJECT_PLAN.md)。
2. 閱讀 [M0 結果](docs/m0-status.md) 與 [M1 計畫](docs/m1-plan.md)。
3. 查看 GitHub Issues 中標示 `good first issue` 或 `help wanted` 的任務。
4. 在 Issue 留言認領後再開始實作，避免重工。
5. 遵循 [CONTRIBUTING.md](CONTRIBUTING.md) 提交 Pull Request。

## 已知限制

- 目前 spike 是 Node.js 腳本，正式量化研究技術棧仍待 M1 決策。
- 價格尚未完成除權息還原，不可直接作正式績效結論。
- 歷史股票池、下市股票與有效期間尚未完成。
- 法人與融資尚未完成官方值抽樣對帳。
- 大量原始資料不提交至公開 repository。

## 最近 Commit

- `5fb2b8a` — 完成 M0 資料可行性 spike。
- `0bfc056` — 建立完整專案計畫。
