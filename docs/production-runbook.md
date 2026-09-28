# QMO 快速上線 Runbook

## 部署前最低門檻

- Production `qmo update` 必須使用真實 Provider；不得使用 synthetic fallback。
- `.env` 僅存於主機，不得提交 Git；缺少必要憑證時更新命令必須失敗。
- `latest` 由台北時區、盤後截止時間及休市日曆解析，Provider 空資料仍須視為失敗。
- `data` 使用持久化 Volume；更新失敗不得覆蓋上一個成功批次。

## 建置與基本驗收

```bash
docker compose build --pull
docker compose run --rm qmo --version
docker compose run --rm qmo status --root-dir /var/lib/qmo/data
docker compose run --rm qmo update --date latest --dry-run --root-dir /var/lib/qmo/data
```

確認真實 Provider 已接線後才可執行非 dry-run 更新：

```bash
docker compose run --rm qmo update --date latest --root-dir /var/lib/qmo/data
docker compose run --rm qmo validate --root-dir /var/lib/qmo/data --format text
```

任一步驟非零退出即停止，不得以舊資料冒充當日更新成功。

## 排程

將 repository 放置於 `/opt/quant-market-observer`，主機時區設為
`Asia/Taipei`，再安裝 `deploy/qmo.cron`。更新使用 `flock` 防止重疊執行。

## 回滾

1. 停用 cron。
2. 將 `QMO_IMAGE_TAG` 指回前一個已驗證映像版本。
3. 執行 `docker compose run --rm qmo status`，確認 DuckDB Catalog 仍指向前一個成功批次。
4. 不要手動覆寫或刪除已發布批次；由 manifest 與 atomic publisher 維持不可變性。

## 監控最低要求

- Cron 非零退出必須送達外部告警系統。
- 每日檢查三個 dataset 的最新批次日期、股票覆蓋數與 Quality Gate 結果。
- API 429、5xx、空回應、股票池驟減及資料日期落後均應告警，且禁止發布。
