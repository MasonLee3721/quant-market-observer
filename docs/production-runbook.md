# QMO 快速上線 Runbook

## 部署前最低門檻

- Production `qmo update` 必須使用真實 Provider 模式 (`--provider-mode official-bulk`)；不得使用 synthetic fallback。
- `.env` 僅存於主機，不得提交 Git；`QMO_IMAGE_TAG` 必須固定於驗證通過之 Git Commit Hash (例：`QMO_IMAGE_TAG=7f02840`)。
- `latest` 由台北時區、盤後截止時間及休市日曆解析，Provider 空資料或日期不符仍須 Fail-Closed 視為失敗。
- `data` 使用持久化 Volume；更新失敗不得覆蓋上一個成功批次。

## 建置與基本驗收

```bash
# 1. 建置並固定映像版本 (請替換為當前通過驗收之 Git Commit Hash)
docker build -t quant-market-observer:COMMIT_HASH .

# 2. 安全更新 .env 設定檔（勿直接使用 > 覆寫既有 .env）
grep -q "^QMO_IMAGE_TAG=" .env 2>/dev/null && sed -i 's/^QMO_IMAGE_TAG=.*/QMO_IMAGE_TAG=COMMIT_HASH/' .env || echo "QMO_IMAGE_TAG=COMMIT_HASH" >> .env
grep -q "^DISCORD_WEBHOOK_URL=" .env 2>/dev/null || echo "DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/..." >> .env

# 3. 驗收 CLI 與 Catalog 狀態
docker compose run --rm qmo status --root-dir /var/lib/qmo/data
docker compose run --rm qmo update --provider-mode official-bulk --holiday-calendar /opt/quant-market-observer/config/taiwan_holidays.csv --date latest --dry-run --root-dir /var/lib/qmo/data
```

確認真實 Provider 已接線後才可執行非 dry-run 更新：

```bash
docker compose run --rm qmo update --provider-mode official-bulk --holiday-calendar /opt/quant-market-observer/config/taiwan_holidays.csv --date latest --root-dir /var/lib/qmo/data
docker compose run --rm qmo validate --root-dir /var/lib/qmo/data --format text
```

任一步驟非零退出即停止，不得以舊資料冒充當日更新成功。

## 排程與告警

將 repository 放置於 `/opt/quant-market-observer`，主機時區設為 `Asia/Taipei`，再安裝 `deploy/qmo.cron`。
排程呼叫 `deploy/run_pipeline.sh`，使用單一共用鎖 `/var/lock/qmo-pipeline.lock` 原子性執行 update 與 validate。
若任一步驟失敗（非零退出），會自動觸發 `deploy/notify_alert.sh` 以 Python 進行安全 JSON 編碼並發送外部 Webhook 告警。

## 備份與還原演練

1. **定期備份 (Daily Backup)**
   - 每日盤後定時將 DuckDB Catalog `/var/lib/qmo/data/catalog/qmo_catalog.duckdb` 與 `normalized/` Parquet 批次同步備份至獨立儲存庫：
   ```bash
   tar -czf /backup/qmo-data-$(date +%Y%m%d).tar.gz -C /var/lib/qmo/data catalog normalized
   ```
2. **還原演練 (Restore Drill)**
   - 若發生極端災害需還原 Catalog 與 Dataset：
   ```bash
   # 1. 暫停 Cron
   crontab -r
   # 2. 解壓備份至資料目錄
   tar -xzf /backup/qmo-data-YYYYMMDD.tar.gz -C /var/lib/qmo/data
   # 3. 執行狀態驗證
   docker compose run --rm qmo status --root-dir /var/lib/qmo/data
   # 4. 重新啟用 Cron
   crontab deploy/qmo.cron
   ```

## 資料與日誌保留策略 (Retention & Log Rotation)

1. **日誌輪替 (Log Rotation)**
   - 安裝 `deploy/qmo-logrotate.conf` 至 `/etc/logrotate.d/qmo`，設定每日輪替並保留 30 天日誌：
   ```bash
   cp deploy/qmo-logrotate.conf /etc/logrotate.d/qmo
   ```
2. **磁碟容量監控 (Disk Capacity Alert)**
   - 監控 `/var/lib/qmo/data` 所在掛載點使用率，超過 80% 觸發警告，超過 90% 觸發緊急告警。

## 回滾與停用

1. 停用 cron (`crontab -r`)。
2. 將 `.env` 中的 `QMO_IMAGE_TAG` 指回前一個已驗證映像版本 (例：`QMO_IMAGE_TAG=7f02840`)。
3. 執行 `docker compose run --rm qmo status`，確認 DuckDB Catalog 仍指向前一個成功批次。
4. 不要手動覆寫或刪除已發布批次；由 manifest 與 atomic publisher 維持不可變性。

## 監控最低要求

- Cron 非零退出自動透過 `deploy/notify_alert.sh` 送達外部 Webhook 告警系統。
- 每日檢查三個 dataset 的最新批次日期、股票覆蓋數與 Quality Gate 結果。
- API 429、5xx、空回應、股票池驟減及資料日期落後均應告警，且禁止發布。


