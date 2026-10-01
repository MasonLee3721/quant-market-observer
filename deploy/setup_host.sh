#!/usr/bin/env bash
set -euo pipefail

# Automated Host Initialization Script for QMO Deployment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DATA_DIR="${DATA_DIR:-/var/lib/qmo/data}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/qmo/backups}"
LOCK_DIR="${LOCK_DIR:-/var/lock/qmo}"
LOG_DIR="${LOG_DIR:-/var/log}"
LOGROTATE_DIR="${LOGROTATE_DIR:-/etc/logrotate.d}"
CRON_DIR="${CRON_DIR:-/etc/cron.d}"

QMO_UID=10001
QMO_GID=10001

echo "=== [1/7] Preflight software dependency inspection ==="
SKIP_PREFLIGHT="${SKIP_PREFLIGHT_CHECK:-0}"
if [ "$SKIP_PREFLIGHT" != "1" ]; then
    MISSING_DEPS=()
    for cmd in docker flock logrotate; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            MISSING_DEPS+=("$cmd")
        fi
    done
    if ! command -v cron >/dev/null 2>&1 && ! command -v crond >/dev/null 2>&1; then
        MISSING_DEPS+=("cron")
    fi
    if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
        echo "ERROR: Required software dependencies missing on host: ${MISSING_DEPS[*]}" >&2
        echo "Please install missing software before running setup_host.sh. Aborting (Fail-Closed)." >&2
        exit 1
    fi
fi

echo "=== [2/7] Validating & creating system group and user qmo (UID/GID: $QMO_UID) ==="
if getent group qmo >/dev/null 2>&1; then
    EXISTING_GID=$(getent group qmo | cut -d: -f3)
    if [ "$EXISTING_GID" -ne "$QMO_GID" ]; then
        echo "ERROR: Group 'qmo' exists with GID $EXISTING_GID, expected $QMO_GID! Fail-Closed." >&2
        exit 1
    fi
else
    groupadd -g "$QMO_GID" qmo 2>/dev/null || true
fi

if getent passwd qmo >/dev/null 2>&1; then
    EXISTING_UID=$(id -u qmo)
    EXISTING_USER_GID=$(id -g qmo 2>/dev/null || getent passwd qmo | cut -d: -f4)
    if [ "$EXISTING_UID" -ne "$QMO_UID" ] || [ "$EXISTING_USER_GID" -ne "$QMO_GID" ]; then
        echo "ERROR: User 'qmo' exists with UID $EXISTING_UID / primary GID $EXISTING_USER_GID, expected $QMO_UID:$QMO_GID! Fail-Closed." >&2
        exit 1
    fi
else
    useradd -u "$QMO_UID" -g "$QMO_GID" -s /bin/false qmo 2>/dev/null || true
fi

echo "=== [3/7] Configuring Docker group permissions for qmo user ==="
if getent group docker >/dev/null 2>&1; then
    usermod -aG docker qmo 2>/dev/null || true
fi

echo "=== [4/7] Verifying host timezone (Asia/Taipei) ==="
if command -v timedatectl >/dev/null 2>&1; then
    CURRENT_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null || echo "")
    if [ "$CURRENT_TZ" != "Asia/Taipei" ]; then
        echo "Setting host timezone to Asia/Taipei..."
        timedatectl set-timezone Asia/Taipei 2>/dev/null || echo "WARNING: Unable to set timezone via timedatectl automatically."
    fi
fi

echo "=== [5/7] Initializing data, backup, lock directories and marker file ==="
if [ -d "$DATA_DIR" ] && [ "$(ls -A "$DATA_DIR" 2>/dev/null)" ] && [ ! -f "$DATA_DIR/.qmo_data_dir" ]; then
    echo "ERROR: Target data directory '$DATA_DIR' exists and is non-empty, but lacks marker file '.qmo_data_dir'! Refusing to initialize (Fail-Closed)." >&2
    exit 1
fi

mkdir -p "$DATA_DIR" "$BACKUP_DIR" "$LOCK_DIR"
if [ ! -f "$DATA_DIR/.qmo_data_dir" ]; then
    touch "$DATA_DIR/.qmo_data_dir"
fi
chown -R "$QMO_UID:$QMO_GID" "$DATA_DIR" "$BACKUP_DIR" "$LOCK_DIR" 2>/dev/null || true
chmod 755 "$DATA_DIR" "$BACKUP_DIR" "$LOCK_DIR"
chmod 600 "$DATA_DIR/.qmo_data_dir"

echo "=== [6/7] Setting up log & .env permissions for qmo user ==="
touch "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log"
chown "$QMO_UID:$QMO_GID" "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log" 2>/dev/null || true
chmod 664 "$LOG_DIR/qmo-pipeline.log" "$LOG_DIR/qmo-backup.log" "$LOG_DIR/qmo-disk.log"

ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
if [ -f "$ENV_FILE" ]; then
    chown "$QMO_UID:$QMO_GID" "$ENV_FILE" 2>/dev/null || true
    chmod 600 "$ENV_FILE"
fi

echo "=== [7/7] Installing logrotate configuration & system cron from template ==="
if [ -d "$LOGROTATE_DIR" ] && [ -f "$SCRIPT_DIR/qmo-logrotate.conf" ]; then
    cp "$SCRIPT_DIR/qmo-logrotate.conf" "$LOGROTATE_DIR/qmo"
    chmod 644 "$LOGROTATE_DIR/qmo"
fi

if [ -d "$CRON_DIR" ] && [ -f "$SCRIPT_DIR/qmo.cron" ]; then
    cp "$SCRIPT_DIR/qmo.cron" "$CRON_DIR/qmo"
    chmod 644 "$CRON_DIR/qmo"
fi

echo "=== Host Setup Completed Successfully ==="
echo "Next steps:"
echo "1. Verify SSH hardening (PasswordAuthentication no, PermitRootLogin no) manually."
echo "2. Create $PROJECT_DIR/.env with DISCORD_WEBHOOK_URL, owned by 10001:10001 with mode 600."
echo "3. Run 'docker compose run --rm qmo status' to verify container bind-mount execution."
