# ADR-0002：由 Node.js M0 Spike 過渡至 Python 3.12 正式資料管線

- 狀態：Accepted
- 日期：2026-09-27

## 背景

在 M0 階段，專案使用 Node.js (`scripts/m0_spike.mjs`) 完成了 50 檔代表性標的、23 個主題、最近兩年價量／法人／融資資料的可行性驗證與權威來源抽樣對帳。
由於後續 M1-M3 包含資料正規化、 Parquet / DuckDB 儲存、品質驗證、市場與族群指標計算及量化策略回測，需要選擇適合正式營運與維護的技術棧。

## 決定

1. **技術棧轉移**：正式資料管線全面採用 **Python 3.12**。
2. **工具鏈選擇**：
   - 專案與依賴管理：`pyproject.toml` (遵循 PEP 621 標準)，支援 `uv` / `pip` 快速安裝。
   - 代碼風格與 Lint：`ruff`
   - 型別檢查：`mypy` (Strict Mode)
   - 單元與整合測試：`pytest`
   - CLI 進入點：`click` (`qmo` 指令)
3. **M0 資產重用與對照測試策略**：
   - 原 Node.js spike 腳本 (`scripts/m0_spike.mjs`) 與驗證檔保留於 repository，作為 Python 管線開發時的對照基準 (Regression Parity Baseline)。
   - M1 Normalizer 產出之標準化資料進行跨語言對照測試時：
     - **離散欄位**（股票代碼 `symbol`、交易日期 `date`、狀態標記 `no_trade` 等）須 **100% 完全一致**。
     - **數值與浮點欄位**：固定單位（價格為元、成交量為股）與捨入政策（Banker's Rounding / Half-to-Even），價格欄位小數點保留至第 2 位，允許 `1e-4` 之浮點容許誤差（Epsilon Tolerance），避免跨語言進位或印出格式差異導致脆弱測試 (Brittle Tests)。


## 理由

- **PyData 生態完整性**：Python 在巨量 Parquet 處理 (PyArrow/Polars)、內嵌式 SQL 引擎 (DuckDB)、型別驗證 (Pydantic) 及後續 M2/M3 回測計算上有極強大的生態支援。
- **嚴謹資料語意**：藉由 Pydantic 與 Python 3.12 的嚴格型別標註，確保 `null` 與 `no_trade` 語意不被自動隱式轉換（防止被誤轉為 `0.0`）。
- **工具鏈輕量高效**：結合 Ruff 與 Mypy 可在 CI/CD 中達到毫秒級檢查速度，確保高程式品質。

## 後果

- **優點**：架構可擴展性（Scalability）大增，後續策略開發者可直接調用 Python API 進行多維度分析。
- **缺點**：需重構 M0 既有 Fetcher 與 Normalizer 為 Python 版本，並維護跨語言測試對照。

## 重新評估條件

若未來 TWSE/TPEx 盤後資料處理遇到單線程效能極限且無法透過 DuckDB / Arrow 解決，或伺服器環境嚴格受限於極端記憶體足跡時重新評估。
