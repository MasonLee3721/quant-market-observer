#!/usr/bin/env bash
set -euo pipefail

# Production Safe QMO Restore Script with Mandatory Checksum, Tar Traversal Defense, Staging Catalog Integrity & Atomic Swap Rollback

TAR_FILE="${1:-}"
DATA_DIR="${2:-/var/lib/qmo/data}"
LOCK_FILE="${LOCK_FILE:-/var/lock/qmo-pipeline.lock}"

if [ -z "$TAR_FILE" ] || [ ! -f "$TAR_FILE" ]; then
    echo "Usage: $0 <path_to_backup_archive.tar.gz> [target_data_dir]" >&2
    exit 1
fi

# 1. Path Traversal, Forbidden Root & Marker File Defense
REAL_DATA_DIR=$(readlink -f "$DATA_DIR" 2>/dev/null || echo "$DATA_DIR")
if [[ "$REAL_DATA_DIR" =~ ^/(bin|boot|dev|etc|home|lib|lib64|proc|root|sbin|sys|tmp|usr|var)?/?$ ]]; then
    echo "ERROR: Refusing to restore to broad system root directory '$REAL_DATA_DIR'!" >&2
    exit 1
fi

if [ -d "$REAL_DATA_DIR" ] && [ "$(ls -A "$REAL_DATA_DIR" 2>/dev/null)" ] && [ ! -f "$REAL_DATA_DIR/.qmo_data_dir" ]; then
    echo "ERROR: Existing target directory '$REAL_DATA_DIR' is missing marker file '.qmo_data_dir'! Refusing restore to unverified target." >&2
    exit 1
fi

# 2. Strict Checksum Verification (Mandatory)
SHA_FILE="$TAR_FILE.sha256"
if [ ! -f "$SHA_FILE" ]; then
    echo "ERROR: Mandatory SHA256 checksum file '$SHA_FILE' is missing! Restore aborted." >&2
    exit 1
fi

echo "Verifying SHA256 checksum for $TAR_FILE..."
BACKUP_DIR=$(dirname "$TAR_FILE")
(cd "$BACKUP_DIR" && sha256sum -c "$(basename "$SHA_FILE")") || {
    echo "ERROR: SHA256 checksum verification failed for $TAR_FILE! Archive may be corrupted or tampered." >&2
    exit 1
}

# 3. Archive Path Traversal & Dangerous Symlink Inspection
if tar -tf "$TAR_FILE" | grep -E -- '(\.\./|^/)' >/dev/null || tar -tvf "$TAR_FILE" | grep -E -- '-> /|-> .*\.\.' >/dev/null; then
    echo "ERROR: Archive contains unsafe absolute path, path traversal, or dangerous symlink target! Restore aborted." >&2
    exit 1
fi

# 4. Exclusive Lock
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "ERROR: Cannot perform restore - pipeline is running under $LOCK_FILE" >&2
    exit 1
fi

PARENT_DIR=$(dirname "$REAL_DATA_DIR")
mkdir -p "$PARENT_DIR"
STAGING_DIR=$(mktemp -d -p "$PARENT_DIR" qmo-restore-staging-XXXXXX)
ROLLBACK_DIR="$REAL_DATA_DIR.rollback_$(date +%Y%m%d_%H%M%S)"

cleanup() {
    local exit_code=$?
    if [ -n "${STAGING_DIR:-}" ] && [ -d "$STAGING_DIR" ]; then
        rm -rf "$STAGING_DIR" 2>/dev/null || true
    fi
    if [ $exit_code -ne 0 ] && [ -n "${ROLLBACK_DIR:-}" ] && [ -d "$ROLLBACK_DIR" ] && [ ! -d "$REAL_DATA_DIR" ]; then
        echo "ERROR: Restoring original data directory from $ROLLBACK_DIR due to failure..." >&2
        mv "$ROLLBACK_DIR" "$REAL_DATA_DIR" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "=== Extracting backup archive to staging directory $STAGING_DIR ==="
tar -xzf "$TAR_FILE" -C "$STAGING_DIR"

if [ ! -f "$STAGING_DIR/.qmo_data_dir" ]; then
    echo "ERROR: Restored backup archive is missing required marker file '.qmo_data_dir'! Restore aborted." >&2
    exit 1
fi

# 5. Mandatory Staging Catalog Integrity Validation
if [ -f "$STAGING_DIR/catalog/qmo_catalog.duckdb" ]; then
    echo "Running mandatory integrity check on restored staging DuckDB catalog..."
    PYTHON_BIN=$(command -v python3 || command -v python || echo "python3")
    if ! $PYTHON_BIN -c "import duckdb; conn = duckdb.connect('$STAGING_DIR/catalog/qmo_catalog.duckdb', read_only=True); tables = [t[0] for t in conn.execute('SHOW TABLES').fetchall()]; assert 'batch_manifests' in tables and 'quality_reports' in tables, f'Missing required tables: {tables}'; conn.execute('SELECT count(*) FROM batch_manifests').fetchall(); conn.execute('SELECT count(*) FROM quality_reports').fetchall(); print('Staging DuckDB catalog integrity check PASSED')"; then
        echo "ERROR: DuckDB catalog integrity check failed for staging data! Restore aborted." >&2
        exit 1
    fi
else
    echo "ERROR: Restored staging directory missing catalog/qmo_catalog.duckdb! Restore aborted." >&2
    exit 1
fi

# 6. Atomic Directory Swap with Automated Rollback
echo "=== Performing atomic directory swap of $REAL_DATA_DIR ==="
mkdir -p "$REAL_DATA_DIR"

if ! mv "$REAL_DATA_DIR" "$ROLLBACK_DIR"; then
    echo "ERROR: Failed to move existing live data directory to rollback target!" >&2
    exit 1
fi

if [ "${MOCK_FAIL_STAGING_SWAP:-0}" = "1" ]; then
    echo "ERROR: Simulating staging swap failure for rollback test..." >&2
    rm -rf "$STAGING_DIR"
fi

if ! mv "$STAGING_DIR" "$REAL_DATA_DIR"; then
    echo "ERROR: Failed to swap staging directory to live target! Performing automatic rollback..." >&2
    mv "$ROLLBACK_DIR" "$REAL_DATA_DIR" 2>/dev/null || true
    exit 1
fi

# 7. Cleanup Rollback Directory on Clean Success
rm -rf "$ROLLBACK_DIR"
ROLLBACK_DIR=""
echo "=== QMO Restore Completed Successfully ==="
