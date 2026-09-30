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

放置 repository 於 `/opt/quant-market-observer`，主機時區設為 `Asia/Taipei`。
建立固定數值 UID/GID 之 `qmo` 使用者與群組 (`groupadd -g 10001 qmo && useradd -u 10001 -g 10001 -s /bin/false qmo`)，確保與 Docker 容器內 `10001:10001` 完全一致。
初始化資料目錄並設定權限與標記檔：
```bash
mkdir -p /var/lib/qmo/data /var/lib/qmo/backups
touch /var/lib/qmo/data/.qmo_data_dir
chown -R 10001:10001 /var/lib/qmo
```
安裝 `deploy/qmo.cron` 至 crontab：
- `run_pipeline.sh`: 盤後原子執行 update 與 validate，持有 `/var/lock/qmo-pipeline.lock` 共用鎖。
- `backup_qmo.sh`: 每日定時將 Host Bind Mount 資料目錄打包並生成 `.sha256` 驗證碼，自動清理 30 天舊備份。
- `check_disk_space.sh`: 每小時監控 Host 資料 Volume 容量 (80% Warning / 90% Critical 告警)。

## 備份與還原演練

1. **定期備份 (Daily Backup)**
   - Cron 排程自動呼叫 `deploy/backup_qmo.sh /var/lib/qmo/data /var/lib/qmo/backups`。
   - 生成打包檔與 `.sha256` 校驗檔，確保無崩潰或資料毀損。
2. **安全還原演練 (Atomic Safe Restore)**
   - 執行原子還原腳本 `deploy/restore_qmo.sh`：
   ```bash
   # 1. 檢查備份檔與 SHA256 驗證碼
   deploy/restore_qmo.sh /var/lib/qmo/backups/qmo-backup-YYYYMMDD_HHMMSS.tar.gz /var/lib/qmo/data
   # 2. 驗收 DuckDB Catalog 狀態
   docker compose run --rm qmo status --root-dir /var/lib/qmo/data
   ```
   - 還原腳本會自動進行：SHA256 強制校驗、Tar Traversal / 危險 Symlink 防護、Staging DuckDB Catalog `batch_manifests` & `quality_reports` 查詢測試、同 Filesystem 原子 Rename 切換，若有任一步驟異常即自動 Rollback 復原原目錄。

## 資料與日誌保留策略 (Retention & Log Rotation)

1. **日誌輪替 (Log Rotation)**
   - 確保 Host 系統已有 `qmo:qmo` 使用者與群組，將 `deploy/qmo-logrotate.conf` 安裝至 `/etc/logrotate.d/qmo`：
   ```bash
   cp deploy/qmo-logrotate.conf /etc/logrotate.d/qmo
   ```
2. **磁碟容量監控 (Disk Capacity Alert)**
   - 監控 `/var/lib/qmo/data` 所在掛載點使用率，超過 80% 觸發 Warning，超過 90% 觸發 Critical 告警。

## 回滾與停用

1. 停用 cron (`crontab -r`)。
2. 將 `.env` 中的 `QMO_IMAGE_TAG` 指回前一個已驗證映像版本 (例：`QMO_IMAGE_TAG=7f02840`)。
3. 執行 `docker compose run --rm qmo status`，確認 DuckDB Catalog 仍指向前一個成功批次。
4. 不要手動覆寫或刪除已發布批次；由 manifest 與 atomic publisher 維持不可變性。

## 監控最低要求

- Cron 非零退出自動透過 `deploy/notify_alert.sh` 送達外部 Webhook 告警系統。
- 每日檢查三個 dataset 的最新批次日期、股票覆蓋數與 Quality Gate 結果。
- API 429、5xx、空回應、股票池驟減及資料日期落後均應告警，且禁止發布。


