"""DuckDB Catalog Metadata Indexer implementation with schema migrations."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

from qmo.storage.manifest import BatchManifest, BatchStatus


class BatchConflictError(Exception):
    """Raised when overwriting an existing published batch with conflicting content."""


class DuckDBCatalog:
    """Indexed metadata catalog powered by DuckDB for published batches."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is not None:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = duckdb.connect(str(self.db_path))
        else:
            self.conn = duckdb.connect(":memory:")

        self._init_and_migrate_schema()

    def _init_and_migrate_schema(self) -> None:
        """Create catalog metadata tables and automatically migrate legacy schema if present."""
        res = self.conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'batch_manifests'"
        ).fetchone()
        table_exists = res is not None and res[0] > 0

        if table_exists:
            # Inspect existing columns
            info = self.conn.execute("PRAGMA table_info('batch_manifests')").fetchall()
            cols = [r[1] for r in info]
            needs_migration = "parquet_file_hashes" not in cols

            if needs_migration:
                # Migrate legacy schema to new composite primary key (dataset, batch_id) table
                self.conn.execute("ALTER TABLE batch_manifests RENAME TO legacy_batch_manifests")
                self._create_tables()
                self._migrate_legacy_rows()
                self.conn.execute("DROP TABLE legacy_batch_manifests")
        else:
            self._create_tables()

    def _create_tables(self) -> None:
        """Create standard catalog tables."""
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_manifests (
                dataset VARCHAR NOT NULL,
                batch_id VARCHAR NOT NULL,
                source_raw_hashes VARCHAR NOT NULL,
                schema_version VARCHAR NOT NULL,
                record_count BIGINT NOT NULL,
                partition_date_range VARCHAR,
                created_at VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                published_filepaths VARCHAR NOT NULL,
                parquet_file_hashes VARCHAR NOT NULL,
                manifest_hash VARCHAR NOT NULL,
                PRIMARY KEY (dataset, batch_id)
            );
            """
        )

    def _migrate_legacy_rows(self) -> None:
        """Migrate rows from legacy_batch_manifests if present."""
        try:
            legacy_rows = self.conn.execute("SELECT * FROM legacy_batch_manifests").fetchall()
            for row in legacy_rows:
                # Handle legacy table structure safely
                b_id = row[0]
                ds = row[1] if len(row) > 1 else "unknown"
                raw_h = row[2] if len(row) > 2 else "[]"
                s_ver = row[3] if len(row) > 3 else "schema-v0.1"
                r_cnt = row[4] if len(row) > 4 else 0
                p_range = row[5] if len(row) > 5 else None
                c_at = row[6] if len(row) > 6 else ""
                st = row[7] if len(row) > 7 else "PUBLISHED"
                p_files = row[8] if len(row) > 8 else "[]"
                m_hash = row[9] if len(row) > 9 else ""
                pq_hashes = "{}"

                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO batch_manifests (
                        dataset, batch_id, source_raw_hashes, schema_version,
                        record_count, partition_date_range, created_at, status,
                        published_filepaths, parquet_file_hashes, manifest_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (ds, b_id, raw_h, s_ver, r_cnt, p_range, c_at, st, p_files, pq_hashes, m_hash),
                )
        except Exception:
            pass

    def register_published_batch(self, manifest: BatchManifest) -> None:
        """Register a published batch manifest in DuckDB catalog using transaction safety.

        Raises ValueError if batch status is not PUBLISHED.
        Raises BatchConflictError if batch already exists with conflicting content.
        Raises FileNotFoundError if published files or hashes are missing/corrupted.
        """
        if manifest.status != BatchStatus.PUBLISHED:
            raise ValueError(
                f"Cannot register batch with non-PUBLISHED status: {manifest.status}"
            )

        for filepath in manifest.published_filepaths:
            p = Path(filepath)
            if not p.exists():
                raise FileNotFoundError(
                    f"Catalog indexing error: Published file does not exist at {p}"
                )
            expected_hash = (
                manifest.parquet_file_hashes.get(str(p))
                or manifest.parquet_file_hashes.get(p.name)
            )
            if expected_hash:
                actual_hash = hashlib.sha256(p.read_bytes()).hexdigest()
                if actual_hash != expected_hash:
                    raise ValueError(
                        f"Catalog verification error: Published file hash mismatch for {p}. "
                        f"Expected {expected_hash}, got {actual_hash}"
                    )

        # Check existing DB record for composite key (dataset, batch_id)
        existing = self.conn.execute(
            "SELECT manifest_hash FROM batch_manifests WHERE dataset = ? AND batch_id = ?",
            (manifest.dataset, manifest.batch_id),
        ).fetchall()

        if existing:
            existing_hash = existing[0][0]
            if existing_hash == manifest.manifest_hash:
                # Idempotent re-submission: identical content, do nothing
                return
            else:
                err_msg = (
                    f"Batch '{manifest.batch_id}' in dataset '{manifest.dataset}' "
                    f"already exists with conflicting manifest_hash ({existing_hash})"
                )
                raise BatchConflictError(err_msg)

        raw_hashes_json = json.dumps(manifest.source_raw_hashes)
        filepaths_json = json.dumps(manifest.published_filepaths)
        parquet_hashes_json = json.dumps(manifest.parquet_file_hashes)

        try:
            self.conn.execute("BEGIN TRANSACTION")
            self.conn.execute(
                """
                INSERT INTO batch_manifests (
                    dataset, batch_id, source_raw_hashes, schema_version,
                    record_count, partition_date_range, created_at, status,
                    published_filepaths, parquet_file_hashes, manifest_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    manifest.dataset,
                    manifest.batch_id,
                    raw_hashes_json,
                    manifest.schema_version,
                    manifest.record_count,
                    manifest.partition_date_range,
                    manifest.created_at,
                    manifest.status.value,
                    filepaths_json,
                    parquet_hashes_json,
                    manifest.manifest_hash,
                ),
            )
            self.conn.execute("COMMIT")
        except Exception as e:
            self.conn.execute("ROLLBACK")
            raise e

    def get_batch_manifest(self, dataset: str, batch_id: str) -> Optional[BatchManifest]:
        """Fetch batch manifest from DuckDB catalog by composite key (dataset, batch_id)."""
        rel = self.conn.execute(
            "SELECT dataset, batch_id, source_raw_hashes, schema_version, record_count, "
            "partition_date_range, created_at, status, published_filepaths, parquet_file_hashes, "
            "manifest_hash FROM batch_manifests WHERE dataset = ? AND batch_id = ?",
            (dataset, batch_id),
        ).fetchall()
        if not rel:
            return None

        row = rel[0]
        return BatchManifest(
            dataset=row[0],
            batch_id=row[1],
            source_raw_hashes=json.loads(row[2]),
            schema_version=row[3],
            record_count=row[4],
            partition_date_range=row[5],
            created_at=row[6],
            status=BatchStatus(row[7]),
            published_filepaths=json.loads(row[8]),
            parquet_file_hashes=json.loads(row[9]),
            manifest_hash=row[10],
        )

    def list_published_batches(self, dataset: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all published batch metadata records."""
        if dataset:
            query = "SELECT * FROM batch_manifests WHERE dataset = ? ORDER BY created_at DESC"
            rows = self.conn.execute(query, (dataset,)).fetchall()
        else:
            query = "SELECT * FROM batch_manifests ORDER BY created_at DESC"
            rows = self.conn.execute(query).fetchall()

        results = []
        for r in rows:
            results.append(
                {
                    "dataset": r[0],
                    "batch_id": r[1],
                    "source_raw_hashes": json.loads(r[2]),
                    "schema_version": r[3],
                    "record_count": r[4],
                    "partition_date_range": r[5],
                    "created_at": r[6],
                    "status": r[7],
                    "published_filepaths": json.loads(r[8]),
                    "parquet_file_hashes": json.loads(r[9]),
                    "manifest_hash": r[10],
                }
            )
        return results

    def close(self) -> None:
        """Close DuckDB database connection."""
        self.conn.close()
