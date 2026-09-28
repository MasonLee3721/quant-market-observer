# M3 執行計畫：策略訊號、組合配置與自動化報告引擎 (Signal & Report MVP)

## 1. 目標

M3 的目標是基於 M2 產出的量化因子與狀態分類，進行策略過濾、訊號生成、風險權重配置，並產出可供投資決策參考的每日 HTML 儀表板與 Markdown 市場簡報。

## 2. 架構邊界與模組劃分

```text
M2 Indicator Data (data/indicators/)
       │
       ▼
[qmo.signals.engine]      ──► 策略過濾與選股訊號 (LeaderBreakout, EmergingAccumulation)
       │
       ▼
[qmo.signals.portfolio]   ──► 持倉配置與風控規則 (主題分散、集中度上限、停損停利門檻)
       │
       ▼
[qmo.reports.generator]   ──► 每日市場報告與 HTML 儀表板 (Market Score, Theme Heatmap, Signal List)
       │
       ▼
[qmo.cli]                 ──► CLI 整合指令 (`qmo signal`, `qmo report`)
```

## 3. 工作包拆解 (Work Packages)

### M3-WP1：選股策略與訊號生成器 (`qmo.signals.engine`)
- **領頭羊突破策略 (`LeaderBreakoutStrategy`)**：
  - 條件：`state == LEADER` 且 `stock_score >= 80` 且 `above_ma60 == True` 且 `buy_streak >= 2`
- **潛力積累策略 (`EmergingAccumulationStrategy`)**：
  - 條件：`state == EMERGING` 且 `inst_flow_pct >= 80` 且 `ret_20d > 0`
- **槓桿警訊過濾器 (`RiskWarningFilter`)**：
  - 標記 `state == LEVERAGED`（融資高升溫 + 法人低參與）之風險個股。

### M3-WP2：組合配置與風控管理器 (`qmo.signals.portfolio`)
- **個股與族群分散**：單一族群最多選入 2 檔，總投資組合控制在 5~10 檔。
- **權重配置演算法**：依 `stock_score` 加權或等權重配置。
- **風險門檻**：標註停損（如 -7%）與停利（如 +15%）建議。

### M3-WP3：自動化報告與 HTML 儀表板 (`qmo.reports.generator`)
- **Markdown 每日簡報 (`daily_summary.md`)**：包含市場總分、熱門族群、強勢標的與風控警訊。
- **HTML 視覺化儀表板 (`dashboard.html`)**：具備響應式設計、族群熱力圖與訊號卡片。

### M3-WP4：CLI 整合指令與單元測試 (`qmo.cli` & `tests/test_signals.py`)
- CLI 指令：`qmo signal --date <date>` 與 `qmo report --date <date>`
- 單元測試與整合測試全數通過（無未來資訊洩漏、嚴格 Null 處理）。

## 4. Definition of Done
- [ ] 策略選股與風險過濾邏輯 100% 模組化與可測試。
- [ ] 組合配置符合族群上限與分散風險規則。
- [ ] 自動生成高質感 HTML 儀表板與 Markdown 簡報。
- [ ] `pytest`, `mypy` (strict mode), `ruff` 全數綠燈通過。
