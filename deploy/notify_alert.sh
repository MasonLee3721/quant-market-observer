#!/usr/bin/env bash
set -euo pipefail

# QMO Cron Failure External Alert Notifier
# Reads DISCORD_WEBHOOK_URL / ALERT_WEBHOOK_URL from environment or /opt/quant-market-observer/.env

TASK_NAME="${1:-QMO Pipeline Job}"
LOG_FILE="${2:-/var/log/qmo-update.log}"
ENV_FILE="/opt/quant-market-observer/.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

WEBHOOK="${DISCORD_WEBHOOK_URL:-${ALERT_WEBHOOK_URL:-${WEBHOOK_URL:-}}}"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%SZ")
HOSTNAME=$(hostname 2>/dev/null || echo "qmo-host")

TAIL_LOG=""
if [ -f "$LOG_FILE" ]; then
    TAIL_LOG=$(tail -n 15 "$LOG_FILE" | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')
fi

PAYLOAD=$(cat <<EOF
{
  "username": "QMO Alert Bot",
  "content": "⚠️ **[ALERT] $TASK_NAME Failed!**\n- **Host**: \`$HOSTNAME\`\n- **Timestamp**: \`$TIMESTAMP\`\n- **Log File**: \`$LOG_FILE\`\n\`\`\`text\n$TAIL_LOG\n\`\`\`"
}
EOF
)

if [ -n "$WEBHOOK" ]; then
    curl -s -H "Content-Type: application/json" -X POST -d "$PAYLOAD" "$WEBHOOK" >/dev/null 2>&1 || true
    echo "[$TIMESTAMP] Alert sent to webhook for $TASK_NAME failure." >> /var/log/qmo-alert.log
else
    echo "[$TIMESTAMP] ALERT: $TASK_NAME failed! (No DISCORD_WEBHOOK_URL configured)" >> /var/log/qmo-alert.log
fi
