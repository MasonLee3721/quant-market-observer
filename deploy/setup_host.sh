#!/usr/bin/env bash
set -euo pipefail

# Automated Host Initialization Script for QMO Deployment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DATA_DIR="/var/lib/qmo/data"
BACKUP_DIR="/var/lib/qmo/backups"
LOCK_DIR="/var/lock/qmo"
LOG_DIR="/var/log"
QMO_UID=10001
QMO_GID=10001

echo "=== [1/6] Validating & creating system user and group qmo (UID/GID: $QMO_UID) ==="
if getent group qmo >/dev/null 2>&1; then
    EXISTING_GID=$(getent group qmo | cut -d: -f3)
    if [ "$EXISTING_GID" -ne "$QMO_GID" ]; then
        echo "ERROR: Group 'qmo' exists with GID $EXISTING_GID, expected $QMO_GID! Fail-Closed." >&2
        exit 1
    fi
else
    groupadd -g "$QMO_GID" qmo
fi

if getent passwd qmo >/dev/null 2>&1; then
    EXISTING_UID=$(id -u qmo)
    if [ "$EXISTING_UID" -ne "$QMO_UID" ]; then
        echo "ERROR: User 'qmo' exists with UID $EXISTING_UID, expected $QMO_UID! Fail-Closed." >&2
        exit 1
    fi
else
    useradd -u "$QMO_UID" -g "$QMO_GID" -s /bin/false qmo
fi

echo "=== [2/6] Verifying host timezone (Asia/Taipei) ==="
if command -v timedatectl >/dev/null 2>&1; then
    CURRENT_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null || echo "")
    if [ "$CURRENT_TZ" != "Asia/Taipei" ]; then
        echo "Setting host timezone to Asia/Taipei..."
        timedatectl set-timezone Asia/Taipei 2>/dev/null || echo "WARNING: Unable to set timezone via timedatectl automatically."
    fi
fi

echo "=== [3/6] Initializing data, backup, lock directories and marker file ==="
mkdir -p "$DATA_DIR" "$BACKUP_DIR" "$LOCK_DIR"
touch "$DATA_DIR/.qmo_data_dir"
chown -R "$QMO_UID:$QMO_GID" /var/lib/qmo "$LOCK_DIR"
chmod 755 "$DATA_DIR" "$BACKUP_DIR" "$LOCK_DIR"
chmod 600 "$DATA_DIR/.qmo_data_dir"

echo "=== [4/6] Setting up log file permissions for qmo user ==="
touch "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log"
chown "$QMO_UID:$QMO_GID" "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log"
chmod 664 "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log"

echo "=== [5/6] Installing logrotate configuration & system cron ==="
if [ -d /etc/logrotate.d ] && [ -f "$SCRIPT_DIR/qmo-logrotate.conf" ]; then
    cp "$SCRIPT_DIR/qmo-logrotate.conf" /etc/logrotate.d/qmo
    chmod 644 /etc/logrotate.d/qmo
fi

if [ -d /etc/cron.d ] && [ -f "$SCRIPT_DIR/qmo.cron" ]; then
    cat <<EOF > /etc/cron.d/qmo
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
CRON_TZ=Asia/Taipei
TZ=Asia/Taipei

30 18 * * 1-5 qmo /opt/quant-market-observer/deploy/run_pipeline.sh
0 19 * * 1-5 qmo /opt/quant-market-observer/deploy/backup_qmo.sh /var/lib/qmo/data /var/lib/qmo/backups >> /var/log/qmo-backup.log 2>&1 || /opt/quant-market-observer/deploy/notify_alert.sh "QMO Backup Task" /var/log/qmo-backup.log
0 * * * * qmo /opt/quant-market-observer/deploy/check_disk_space.sh /var/lib/qmo/data >> /var/log/qmo-disk.log 2>&1
EOF
    chmod 644 /etc/cron.d/qmo
fi

echo "=== [6/6] Preflight software dependency inspection ==="
for cmd in docker flock logrotate cron; do
    if ! command -v "$cmd" >/dev/null 2>&1 && ! command -v "${cmd}d" >/dev/null 2>&1; then
        echo "WARNING: Command '$cmd' is missing on host. Please ensure it is installed before running QMO." >&2
    fi
done

echo "=== Host Setup Completed Successfully ==="
echo "Next steps:"
echo "1. Verify SSH hardening (PasswordAuthentication no, PermitRootLogin no) manually."
echo "2. Copy production .env with DISCORD_WEBHOOK_URL and chmod 600 .env."
echo "3. Run 'docker compose run --rm qmo status' to verify container bind-mount execution."
