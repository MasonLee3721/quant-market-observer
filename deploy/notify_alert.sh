#!/usr/bin/env bash
set -euo pipefail

# QMO Cron Failure External Alert Notifier
# Reads DISCORD_WEBHOOK_URL / ALERT_WEBHOOK_URL from environment or /opt/quant-market-observer/.env

TASK_NAME="${1:-QMO Pipeline Job}"
LOG_FILE="${2:-/var/log/qmo-pipeline.log}"
ENV_FILE="${3:-/opt/quant-market-observer/.env}"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

WEBHOOK="${DISCORD_WEBHOOK_URL:-${ALERT_WEBHOOK_URL:-${WEBHOOK_URL:-}}}"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%SZ")
HOSTNAME=$(hostname 2>/dev/null || echo "qmo-host")

if [ -z "$WEBHOOK" ]; then
    echo "[$TIMESTAMP] ERROR: Alert delivery failed for '$TASK_NAME': No webhook URL configured!" >&2
    exit 1
fi

PAYLOAD=$(python3 -c "
import json, sys, os

task_name = sys.argv[1]
hostname = sys.argv[2]
timestamp = sys.argv[3]
log_file = sys.argv[4]

tail_log = ''
if os.path.isfile(log_file):
    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            tail_log = ''.join(lines[-15:])
    except Exception as e:
        tail_log = f'Failed to read log file: {e}'

content = f'⚠️ **[ALERT] {task_name} Failed!**\n- **Host**: \`{hostname}\`\n- **Timestamp**: \`{timestamp}\`\n- **Log File**: \`{log_file}\`\n\`\`\`text\n{tail_log}\n\`\`\`'

print(json.dumps({'username': 'QMO Alert Bot', 'content': content}))
" "$TASK_NAME" "$HOSTNAME" "$TIMESTAMP" "$LOG_FILE")

if curl -sS --fail -H "Content-Type: application/json" -X POST -d "$PAYLOAD" "$WEBHOOK" >/dev/null; then
    echo "[$TIMESTAMP] SUCCESS: Alert successfully delivered to webhook for '$TASK_NAME'."
    exit 0
else
    echo "[$TIMESTAMP] ERROR: Failed to deliver alert payload to webhook for '$TASK_NAME'!" >&2
    exit 1
fi
