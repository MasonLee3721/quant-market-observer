#!/usr/bin/env bash
set -euo pipefail

# Automated Host Initialization Script for QMO Deployment

DATA_DIR="/var/lib/qmo/data"
BACKUP_DIR="/var/lib/qmo/backups"
LOG_DIR="/var/log"
QMO_UID=10001
QMO_GID=10001

echo "=== [1/5] Creating system user and group qmo (UID/GID: $QMO_UID) ==="
if ! getent group qmo >/dev/null 2>&1; then
    groupadd -g "$QMO_GID" qmo
fi
if ! getent passwd qmo >/dev/null 2>&1; then
    useradd -u "$QMO_UID" -g "$QMO_GID" -s /bin/false qmo
fi

echo "=== [2/5] Initializing data & backup directories and marker file ==="
mkdir -p "$DATA_DIR" "$BACKUP_DIR"
touch "$DATA_DIR/.qmo_data_dir"
chown -R "$QMO_UID:$QMO_GID" /var/lib/qmo
chmod 755 "$DATA_DIR" "$BACKUP_DIR"
chmod 600 "$DATA_DIR/.qmo_data_dir"

echo "=== [3/5] Setting up log files permissions ==="
touch "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log"
chown "$QMO_UID:$QMO_GID" "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log"
chmod 644 "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log"

echo "=== [4/5] Installing logrotate configuration ==="
if [ -d /etc/logrotate.d ] && [ -f deploy/qmo-logrotate.conf ]; then
    cp deploy/qmo-logrotate.conf /etc/logrotate.d/qmo
    chmod 644 /etc/logrotate.d/qmo
fi

echo "=== [5/5] Host Setup Completed Successfully ==="
echo "Next step: Copy .env file, install crontab with 'crontab deploy/qmo.cron', and verify docker compose run."
