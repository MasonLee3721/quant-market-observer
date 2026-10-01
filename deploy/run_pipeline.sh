#!/usr/bin/env bash
set -euo pipefail

# Atomic QMO Pipeline Runner with Shared Flock Lock & Automatic External Alerting

LOCK_FILE="${LOCK_FILE:-/var/lock/qmo/pipeline.lock}"
ROOT_DIR="${QMO_DATA_ROOT:-/var/lib/qmo/data}"
PROJECT_DIR="${PROJECT_DIR:-/opt/quant-market-observer}"
LOG_FILE="${LOG_FILE:-/var/log/qmo-pipeline.log}"
HOLIDAY_CAL="${HOLIDAY_CAL:-/opt/quant-market-observer/config/taiwan_holidays.csv}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY_SCRIPT="${NOTIFY_SCRIPT:-$SCRIPT_DIR/notify_alert.sh}"

if [ -d "$PROJECT_DIR" ]; then
    cd "$PROJECT_DIR"
fi

run_pipeline_steps() {
    if [ ! -d "$ROOT_DIR" ] || [ ! -f "$ROOT_DIR/.qmo_data_dir" ]; then
        echo "ERROR: Pipeline data root '$ROOT_DIR' does not exist or is missing required marker file '.qmo_data_dir'! Pipeline aborted." >&2
        return 1
    fi

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
    if [ -x "$NOTIFY_SCRIPT" ]; then
        "$NOTIFY_SCRIPT" "QMO Update & Validation Pipeline" "$LOG_FILE" "${ENV_FILE:-.env}" || true
    fi
    exit 1
fi
