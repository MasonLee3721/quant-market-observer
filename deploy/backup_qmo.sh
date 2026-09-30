#!/usr/bin/env bash
set -euo pipefail

# Atomic QMO Backup Script with Checksum Generation & Retention Cleanup

DATA_DIR="${1:-/var/lib/qmo/data}"
BACKUP_DIR="${2:-/var/lib/qmo/backups}"
LOCK_FILE="${LOCK_FILE:-/var/lock/qmo-pipeline.lock}"
RETENTION_DAYS=30

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
TAR_FILE="$BACKUP_DIR/qmo-backup-$TIMESTAMP.tar.gz"
SHA_FILE="$TAR_FILE.sha256"

mkdir -p "$BACKUP_DIR"

if [ ! -d "$DATA_DIR" ]; then
    echo "ERROR: Data directory '$DATA_DIR' does not exist!" >&2
    exit 1
fi

if [ ! -f "$DATA_DIR/.qmo_data_dir" ]; then
    echo "ERROR: Data directory '$DATA_DIR' is missing required marker file '.qmo_data_dir'! Backup aborted." >&2
    exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "ERROR: Backup deferred - pipeline is currently running under $LOCK_FILE" >&2
    exit 1
fi

echo "=== Starting QMO Backup: $TIMESTAMP ==="
tar -czf "$TAR_FILE" -C "$DATA_DIR" .

(cd "$BACKUP_DIR" && sha256sum "$(basename "$TAR_FILE")" > "$(basename "$SHA_FILE")")

echo "Backup created successfully: $TAR_FILE"
echo "Checksum file created: $SHA_FILE"

# Clean up backups older than RETENTION_DAYS
find "$BACKUP_DIR" -name "qmo-backup-*.tar.gz*" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true

echo "=== QMO Backup Completed Successfully ==="
