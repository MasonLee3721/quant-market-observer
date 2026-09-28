# M2 執行計畫：指標計算與量化因子引擎 (Indicator Engine MVP)

## 1. 目標

M2 的目標是將 M1 產出的標準化 Parquet/DuckDB 資料，計算為具備**無未來資訊偏誤 (No Look-Ahead Bias)** 與**橫斷面可比性 (Cross-Sectional Comparable)** 的量化因子、族群輪動分數與個股綜合排名。

## 2. 架構邊界與模組劃分

```text
Standardized Storage (M1 Parquet/DuckDB)
       │
       ▼
[qmo.indicators.features]  ──► 個股單指標 (ret_5d, ma20, buy_streak, foreign_intensity)
       │
       ▼
[qmo.indicators.market]    ──► 全市場指標 (breadth_ma20, advance_ratio, market_score)
       │
       ▼
[qmo.indicators.themes]    ──► 族群輪動與資金集中度 (theme_score, flow_hhi, top1_share)
       │
       ▼
[qmo.indicators.ranker]    ──► 橫斷面 Winsorize/Percentile & 綜合評分 (stock_score, leader/emerging)
```

## 3. 工作包拆解 (Work Packages)

### M2-WP1：基礎因子計算器 (`qmo.indicators.features`)
- **價格動能與波動**：`ret_5d`, `ret_20d`, `ret_60d`, `above_ma20`, `above_ma60`, `turnover_20d`, `volume_ratio_5_20`, `volatility_20d`, `drawdown_60d`
- **法人與融資槓桿**：`foreign_net`, `trust_net`, `dealer_net`, `inst_net_5d`, `foreign_intensity_5d`, `buy_streak`, `margin_balance_chg_5d`, `margin_dependency`
- **驗收標準**：視窗未達最小樣本數時回傳 `Null`，分母為零回傳 `Null`。

### M2-WP2：市場與族群聚合器 (`qmo.indicators.market` & `themes`)
- **市場層級**：`breadth_ma20`, `breadth_ma60`, `advance_ratio`, `market_turnover_ratio`, `market_score` (30% 指數 + 25% 廣度 + 15% 熱度 + 20% 法人 + 10% 低槓桿)
- **族群層級**：`theme_relative_strength_20d`, `theme_flow_intensity_5d`, `theme_breadth_20d`, `theme_turnover_ratio`, `theme_margin_quality`, `theme_score`
- **資金集中度**：`top1_share`, `top2_share`, `positive_breadth`, `flow_hhi`

### M2-WP3：橫斷面排名與狀態分類器 (`qmo.indicators.ranker`)
- **因子正規化**：Winsorize 極端值處理，當日可投資股票 Cross-sectional Percentile (0~100)
- **個股綜合評分**：`stock_score` = 35% 法人資金 + 30% 動能 + 20% 流動性 + 15% 風險品質
- **五大狀態分類**：`leader` / `emerging` / `leveraged` / `watch` / `excluded`

### M2-WP4：單元測試與 Parity 驗收 (`tests/test_indicators.py`)
- 公式數值精準度測試
- 滾動視窗、缺值極限與 Look-ahead 防護測試
- M0 雙語言對照驗證

## 4. Definition of Done
- [ ] 完整計算 24+ 種基礎與衍生因子，無未來資訊洩漏。
- [ ] 視窗未滿或分母為零正確回傳 `Null`。
- [ ] 橫斷面評分與狀態分類 100% 覆蓋。
- [ ] `pytest`, `mypy` (strict mode), `ruff` 全數綠燈通過。
