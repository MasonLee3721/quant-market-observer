# Project Status

最後更新：2026-09-28<br>
目前階段：**50 檔代表性個股池之量化市場觀察 MVP／研究驗證版（向全市場生產環境升級中）**

## 一句話狀態

M1 (資料管線 MVP)、M2 (量化指標引擎 MVP)、M3 (策略訊號與 HTML 儀表板) 核心功能與 103 項單元測試 100% 驗證通過；目前為 50 檔代表性個股之 MVP 研究驗證版，正在升級全台股上市櫃 1,000+ 檔真實盤後 API 自動化採集與部署管線。

## 里程碑

| 里程碑 | 狀態 | 主要成果 |
|---|---|---|
| M0 研究規格與資料可行性 | ✅ 完成 | 資料契約、指標字典、50 檔 spike、官方抽樣對帳 |
| M1 資料管線 MVP | ✅ 完成 | Provider、Normalizer、Validator、Storage (Parquet/DuckDB)、Atomic Publisher |
| M2 量化指標與狀態分類引擎 | ✅ 完成 | 5 大狀態分類 (Leader/Emerging/Leveraged/Watch/Excluded)、Percentile 評分 |
| M3 策略訊號與 HTML 儀表板 | ✅ 完成 | 領頭羊/新興選股策略、風控持倉、`daily_summary.md` 與 `dashboard.html` 儀表板 |
| M4 全台股上市櫃全量真實 API 採集 | 🔜 進行中 | `TaiwanStockInfo` 動態 Universe、真實 API Rate Limit 重試與不斷點回補 |
| M5 正式營運部署與自動排程 | 🔜 規劃中 | Docker/Cron 排程、秘密管理、系統健康監控告警 |

## 已驗證事實

- 價量、法人與融資三個 dataset 均覆蓋 50/50 檔。
- 價量資料 24,193 筆，主鍵重複為 0。
- 三表同日完整 join 比率為 99.58%。
- 3 筆無成交資料已轉為 `null` 並標記 `no_trade`。
- TWSE 2330 與 TPEx 8069 的 OHLC、成交股數與成交金額完全一致。
- FinLab 不是必要依賴；TWSE／TPEx 為權威來源，FinMind 為歷史整合層。

## M1 工作包與認領入口

1. [✅ #1 Python 專案骨架與工具鏈](https://github.com/MasonLee3721/quant-market-observer/issues/1) (已由 蘇荃 完成)
2. [#2 FinMind、TWSE、TPEx Providers](https://github.com/MasonLee3721/quant-market-observer/issues/2) (進行中)
3. [#3 資料模型與 Normalizer](https://github.com/MasonLee3721/quant-market-observer/issues/3) (進行中)
4. [#4 Parquet、DuckDB 與批次追蹤](https://github.com/MasonLee3721/quant-market-observer/issues/4) (預計交辦 小寶)
5. [#5 Validator 與官方對帳](https://github.com/MasonLee3721/quant-market-observer/issues/5) (預計交辦 小寶)
6. [#6 CLI、runbook 與上手流程](https://github.com/MasonLee3721/quant-market-observer/issues/6)




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
