#!/usr/bin/env bash
set -euo pipefail

# QMO Disk Capacity Monitoring Script (80% warning / 90% critical alert)

DATA_DIR="${1:-/var/lib/qmo/data}"
WARN_THRESHOLD=80
CRIT_THRESHOLD=90

if [ ! -d "$DATA_DIR" ]; then
    DATA_DIR="/"
fi

USAGE_PCT="${MOCK_USAGE_PCT:-$(df -P "$DATA_DIR" | tail -n 1 | awk '{print $5}' | tr -d '%')}"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%SZ")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY_SCRIPT="${NOTIFY_SCRIPT:-$SCRIPT_DIR/notify_alert.sh}"

ENV_FILE="${ENV_FILE:-/opt/quant-market-observer/.env}"

if [ "$USAGE_PCT" -ge "$CRIT_THRESHOLD" ]; then
    MSG="CRITICAL: Disk space for $DATA_DIR at $USAGE_PCT% (>= $CRIT_THRESHOLD%)!"
    echo "[$TIMESTAMP] $MSG" >&2
    if [ -x "$NOTIFY_SCRIPT" ]; then
        "$NOTIFY_SCRIPT" "Disk Space Critical Alert" /var/log/qmo-pipeline.log "$ENV_FILE" || true
    fi
    exit 1
elif [ "$USAGE_PCT" -ge "$WARN_THRESHOLD" ]; then
    MSG="WARNING: Disk space for $DATA_DIR at $USAGE_PCT% (>= $WARN_THRESHOLD%)"
    echo "[$TIMESTAMP] $MSG"
    if [ -x "$NOTIFY_SCRIPT" ]; then
        "$NOTIFY_SCRIPT" "Disk Space Warning Alert" /var/log/qmo-pipeline.log "$ENV_FILE" || true
    fi
    exit 0
else
    echo "[$TIMESTAMP] OK: Disk space for $DATA_DIR at $USAGE_PCT%"
    exit 0
fi
