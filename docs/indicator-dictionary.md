# M0 指標與公式字典

版本：`indicator-v0.1`

## 共通規則

- 所有日資料依股票、交易日排序後計算。
- T 日收盤後才完整的欄位，最早只能形成 T+1 可執行訊號。
- 比較不同股票時優先使用比例、成交額標準化或橫斷面百分位，而非絕對金額。
- rolling window 未達最小樣本數時回傳缺值，不以零補齊。
- 分母為零或缺值時回傳缺值並記錄品質旗標。

## 價格與流動性

| ID | 名稱 | 公式 | 用途 |
|---|---|---|---|
| `ret_5d` | 5 日報酬 | `close_t / close_t-5 - 1` | 短期動能 |
| `ret_20d` | 20 日報酬 | `close_t / close_t-20 - 1` | 中短期動能 |
| `ret_60d` | 60 日報酬 | `close_t / close_t-60 - 1` | 中期趨勢 |
| `above_ma20` | 月線之上 | `close > SMA(close, 20)` | 市場廣度／趨勢 |
| `above_ma60` | 季線之上 | `close > SMA(close, 60)` | 市場廣度／趨勢 |
| `turnover_20d` | 20 日平均成交額 | `mean(trading_money, 20)` | 流動性門檻 |
| `volume_ratio_5_20` | 量能比 | `mean(volume,5) / mean(volume,20)` | 成交加速 |
| `volatility_20d` | 20 日年化波動 | `std(daily_return,20) × sqrt(252)` | 風險品質 |
| `drawdown_60d` | 60 日回撤 | `close / rolling_max(close,60) - 1` | 高檔與風險 |

## 法人與槓桿

法人原始資料以股數為準；若需金額，M0 暫以 `net_shares × close` 估算並標示為估算值，不宣稱為官方成交金額。

| ID | 名稱 | 公式 | 用途 |
|---|---|---|---|
| `foreign_net` | 外資淨買賣股數 | `foreign_buy - foreign_sell` | 外資方向 |
| `trust_net` | 投信淨買賣股數 | `trust_buy - trust_sell` | 投信方向 |
| `dealer_net` | 自營商淨買賣股數 | 各自營商類別淨額加總 | 自營商方向 |
| `inst_net_5d` | 法人 5 日淨額 | `sum(all_institution_net,5)` | 資金滾動 |
| `foreign_intensity_5d` | 外資資金強度 | `sum(foreign_net × close,5) / sum(trading_money,5)` | 跨股票比較 |
| `buy_streak` | 連續買超日數 | 自最近交易日向前連續 `net > 0` 天數 | 穩定性 |
| `margin_balance_chg_5d` | 融資餘額 5 日變化率 | `balance_t / balance_t-5 - 1` | 槓桿升溫 |
| `margin_dependency` | 融資依賴 | 融資變化橫斷面百分位，方向愈高品質分愈低 | 風險品質 |

## 市場狀態

| ID | 定義 |
|---|---|
| `breadth_ma20` | 可投資股票中 `above_ma20=True` 的比例 |
| `breadth_ma60` | 可投資股票中 `above_ma60=True` 的比例 |
| `advance_ratio` | 上漲家數／有效股票家數 |
| `market_turnover_ratio` | 全市場 5 日平均成交額／20 日平均成交額 |
| `market_score` | 各市場因子 winsorize、百分位化後加權至 0–100 |

市場分數初始權重：指數趨勢 30%、市場廣度 25%、成交熱度 15%、法人方向 20%、低槓桿品質 10%。權重在完成樣本外驗證前只視為假設。

## 族群輪動

| ID | 定義 |
|---|---|
| `theme_relative_strength_20d` | 族群等權 20 日報酬減市場等權 20 日報酬 |
| `theme_flow_intensity_5d` | 族群 5 日法人估算淨額／族群 5 日成交額 |
| `theme_breadth_20d` | 族群內 `ret_20d > 0` 的有效家數比例 |
| `theme_turnover_ratio` | 族群 5 日平均成交額／20 日平均成交額 |
| `theme_margin_quality` | `1 - 融資變化率百分位` |
| `theme_score` | 資金 30%＋相對強度 25%＋廣度 20%＋成交 15%＋低融資 10% |

## 集中度

只在族群淨流入為正且至少兩檔具有有效法人資料時解讀集中度。

| ID | 公式 |
|---|---|
| `top1_share` | 最大正流入／所有正流入合計 |
| `top2_share` | 前二正流入／所有正流入合計 |
| `positive_breadth` | 正流入家數／法人資料有效家數 |
| `flow_hhi` | 各正流入股票占比平方和 |

`flow_hhi` 越高代表資金越集中，但集中不等同優劣；必須搭配價格趨勢、廣度與融資品質判讀。

## 個股排名

MVP 無基本面因子時的暫定權重：

```text
stock_score =
  35% × institutional_flow_score
+ 30% × momentum_score
+ 20% × liquidity_score
+ 15% × risk_quality_score
```

每個子分數採當日可投資股票的橫斷面百分位。流動性最低門檻未通過、價格缺值或資料過期者不參與排名。

## 狀態分類草案

- `leader`：族群前 20%、個股前 20%、`ret_20d > 0`、`above_ma60`。
- `emerging`：5 日資金分數前 20%，但 `ret_20d` 介於市場中位數與前 30% 之間。
- `leveraged`：動能為正、融資增幅前 10%、法人資金低於中位數。
- `watch`：部分訊號成立，但未通過完整條件。
- `excluded`：流動性、資料品質或可交易性不合格。

所有門檻均須在 Phase 3 做參數鄰域與樣本外測試。
