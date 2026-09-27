# Contributing

感謝參與 Quant Market Observer。本專案重視研究可重現性與資料語意，正確性優先於功能數量。

## 開始前

1. 閱讀 `STATUS.md`、`PROJECT_PLAN.md` 與對應里程碑文件。
2. 搜尋是否已有相同 Issue。
3. 在 Issue 留言認領範圍，避免與他人重疊。
4. 大型架構、資料來源、公式或 schema 變更必須先建立 ADR／討論 Issue。

## Branch 與 Commit

- Branch：`feat/<topic>`、`fix/<topic>`、`docs/<topic>`、`research/<topic>`。
- Commit 採簡潔 Conventional Commits，例如 `feat: add tpex price provider`。
- 一個 PR 解決一個清楚問題，避免混入無關格式化。

## Pull Request 必須包含

- 問題與解法摘要。
- 影響的資料、公式或 schema。
- 測試方式與結果。
- 是否需要網路、token 或付費資料。
- 是否存在 look-ahead、授權或公開資料風險。
- 若輸出數字改變，附修改前後比較及原因。

## 資料規則

- 不提交 API token、`.env`、大量原始資料、付費資料或個人投資紀錄。
- 股票代碼維持字串；日期使用 `YYYY-MM-DD`。
- 不把缺值填成零，也不把停牌日以前值偽裝成交易價。
- T 日盤後資料最早形成 T+1 可執行訊號。
- 來源回應與標準化資料分開；raw snapshot 不可覆寫。

## 研究規則

- 先寫假設、公式與否證條件，再看回測結果。
- 必須揭露交易成本、執行價格與基準。
- 失敗結果不刪除；避免只報告最佳參數。
- 新因子要說明市場當時的可得時間，防止未來資料洩漏。

## 本機檢查

```bash
node --check scripts/m0_spike.mjs
node --check scripts/official_spot_check.mjs
node scripts/test_m0.mjs
```

M1 Python 指令會在專案骨架完成後補充。

## Review 原則

依序檢查資料時間正確性、語意與單位、可重現性、測試、效能，最後才是介面便利性。資料來源或公式有疑義時，PR 應保持未合併，直到證據足夠。
