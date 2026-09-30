#!/usr/bin/env bash
set -euo pipefail

# Atomic QMO Pipeline Runner with Shared Flock Lock & Automatic External Alerting

LOCK_FILE="${LOCK_FILE:-/var/lock/qmo-pipeline.lock}"
ROOT_DIR="${QMO_DATA_ROOT:-/var/lib/qmo/data}"
PROJECT_DIR="${PROJECT_DIR:-/opt/quant-market-observer}"
LOG_FILE="/var/log/qmo-pipeline.log"
HOLIDAY_CAL="/opt/quant-market-observer/config/taiwan_holidays.csv"

if [ -d "$PROJECT_DIR" ]; then
    cd "$PROJECT_DIR"
fi

mkdir -p "$ROOT_DIR"
touch "$ROOT_DIR/.qmo_data_dir"

run_pipeline_steps() {
    echo "=== [$(date -u +"%Y-%m-%d %H:%M:%SZ")] Starting QMO Pipeline Update ==="
    docker compose run --rm qmo update \
        --provider-mode official-bulk \
        --holiday-calendar "$HOLIDAY_CAL" \
        --date latest \
        --root-dir "$ROOT_DIR"

    echo "=== [$(date -u +"%Y-%m-%d %H:%M:%SZ")] Starting QMO Pipeline Validation ==="
    docker compose run --rm qmo validate \
        --root-dir "$ROOT_DIR" \
        --format text

    echo "=== [$(date -u +"%Y-%m-%d %H:%M:%SZ")] QMO Pipeline Completed Successfully ==="
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date -u +"%Y-%m-%d %H:%M:%SZ")] QMO Pipeline skipped: another instance is already running under $LOCK_FILE" >> "$LOG_FILE"
    exit 0
fi

if ! run_pipeline_steps >> "$LOG_FILE" 2>&1; then
    echo "[$(date -u +"%Y-%m-%d %H:%M:%SZ")] ERROR: QMO Pipeline failed! Triggering external alert..." >> "$LOG_FILE"
    /opt/quant-market-observer/deploy/notify_alert.sh "QMO Update & Validation Pipeline" "$LOG_FILE" || true
    exit 1
fi
