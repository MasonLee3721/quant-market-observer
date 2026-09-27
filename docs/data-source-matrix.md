# M0 資料來源能力矩陣

最後確認：2026-09-27

## 決策摘要

MVP 不依賴單一商業平台：TWSE／TPEx 是最新盤後資料與抽樣核對的權威來源，FinMind 作為歷史整合層；FinLab 保留為可選 adapter，不是啟動條件。

| 來源 | 用途 | 優點 | 主要限制 | M0 決策 |
|---|---|---|---|---|
| TWSE OpenAPI／報表 | 上市價量、大盤、法人、融資融券 | 官方、最新、適合核對 | 歷史介面分散；格式可能調整；大量重抓需節制 | 權威來源 |
| TPEx 報表／下載 | 上櫃價量、法人、融資融券 | 官方、涵蓋上櫃 | 與 TWSE schema 不同；部分端點偏報表導向 | 權威來源 |
| FinMind API v4 | 統一歷史價量、法人、融資融券 | 上市上櫃格式一致；可按股票查區間 | 第三方；免費額度與服務條款可能變更；初公布資料可能補計 | M0 歷史 spike |
| FinLab | Point-in-time 研究、資料矩陣、回測 | 對齊與回測便利、資料欄位豐富 | 需登入；免費資料只到 2020 年底；最新資料需付費方案 | 選配，不阻塞 MVP |
| MOPS | 月營收、財報與公告 | 官方公司揭露 | 公告日期與資料版本需額外處理 | Phase 6 |
| ETF 發行人／TWSE ETF | PCF、淨值、發行單位 | 官方揭露 | 被動流量仍需推估，PCF 不等於實際成交 | Phase 6 |

## MVP dataset 對照

| 標準資料集 | FinMind dataset | 官方核對 | 更新 | 關鍵欄位 |
|---|---|---|---|---|
| `daily_price` | `TaiwanStockPrice` | TWSE／TPEx 日成交 | 交易日 | OHLC、成交股數、成交金額、成交筆數 |
| `institutional_flow` | `TaiwanStockInstitutionalInvestorsBuySell` | TWSE／TPEx 三大法人 | 交易日盤後 | 法人別、買進股數、賣出股數、淨額 |
| `margin` | `TaiwanStockMarginPurchaseShortSale` | TWSE／TPEx 融資融券 | 交易日盤後 | 融資買賣、現償、餘額；融券對應欄位 |
| `stock_master` | `TaiwanStockInfo` | TWSE／TPEx 股票主檔 | 按需 | 股票代碼、名稱、市場、類型 |

## 更新與定案規則

1. 每日報告只在官方盤後資料預期到齊後執行。
2. 報告必須顯示 `trade_date`、`retrieved_at`、來源與 schema 版本。
3. 當日法人資料可能事後補計；研究快照應保留首次值與重抓值，不能靜默覆蓋。
4. 最新交易日以官方來源核對；歷史批次以 FinMind 取得後做抽樣比對。
5. 缺值、真實零值與來源尚未更新必須分開表示。

## 授權與公開界線

- 公開 repository 只保存程式、公式、少量測試 fixture 與彙總驗證結果。
- 原始大量資料、付費資料與 API 憑證不進 Git。
- API 金鑰只可由環境變數或 GitHub Secrets 注入。
- 任何公開報告在發布前需重新確認來源條款；M0 產出的原始資料只在本機研究使用。

## 已確認限制

- FinLab 非 VIP 帳號依官方 FAQ 僅提供至 2020 年底，無法獨立完成最近兩年 spike。
- FinMind 公開 API 已於 2026-09-27 實測可取得 `2330` 自 2024-09-27 起的日價量資料。
- FinMind 說明法人資料可能在首次公布後微幅更新；若要定案數值，建議交易日後一至兩個營業日重抓。

## M1 前待確認

- TWSE／TPEx 每個正式端點的穩定 URL、回應 schema 與合理請求頻率。
- FinMind 免費額度、重試規則及公開衍生報告的授權邊界。
- 除權息還原價格的正式來源與重建方式。
- 下市、暫停交易與歷史股票池資料來源。
