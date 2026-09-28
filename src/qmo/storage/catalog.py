"""DuckDB Catalog Metadata Indexer implementation with schema migrations."""

import hashlib
import json
from datetime import datetime, timezone
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
            # Inspect existing columns and primary key constraint
            info = self.conn.execute("PRAGMA table_info('batch_manifests')").fetchall()
            cols = [r[1] for r in info]
            pk_cols = {r[1] for r in info if r[5] > 0}
            needs_migration = ("parquet_file_hashes" not in cols) or (
                pk_cols != {"dataset", "batch_id"}
            )

            if needs_migration:
                # Migrate legacy schema inside transaction with row count validation
                self.conn.execute("BEGIN TRANSACTION")
                try:
                    row_cnt_res = self.conn.execute(
                        "SELECT count(*) FROM batch_manifests"
                    ).fetchone()
                    legacy_count = row_cnt_res[0] if row_cnt_res else 0
                    alter_sql = "ALTER TABLE batch_manifests RENAME TO legacy_batch_manifests"
                    self.conn.execute(alter_sql)
                    self._create_tables()
                    migrated_count = self._migrate_legacy_rows()
                    if migrated_count != legacy_count:
                        err_mig = (
                            f"Migration count mismatch: expected {legacy_count}, "
                            f"got {migrated_count}"
                        )
                        raise RuntimeError(err_mig)
                    self.conn.execute("DROP TABLE legacy_batch_manifests")
                    self.conn.execute("COMMIT")
                except Exception as e:
                    self.conn.execute("ROLLBACK")
                    raise RuntimeError(f"Catalog schema migration failed: {e}") from e

            self._create_tables()
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

            CREATE TABLE IF NOT EXISTS quality_reports (
                dataset VARCHAR NOT NULL,
                batch_id VARCHAR NOT NULL,
                overall_passed BOOLEAN NOT NULL,
                created_at VARCHAR NOT NULL,
                total_records BIGINT NOT NULL,
                passed_checks INTEGER NOT NULL,
                total_checks INTEGER NOT NULL,
                report_hash VARCHAR NOT NULL,
                report_json VARCHAR NOT NULL,
                PRIMARY KEY (dataset, batch_id)
            );
            """
        )

    def _migrate_legacy_rows(self) -> int:
        """Migrate rows from legacy_batch_manifests using real file hashes.

        Raises FileNotFoundError if any published file listed in a legacy manifest is missing.
        """
        legacy_rows = self.conn.execute("SELECT * FROM legacy_batch_manifests").fetchall()
        migrated_count = 0
        for row in legacy_rows:
            b_id = row[0]
            ds = row[1] if len(row) > 1 else "unknown"
            raw_h = row[2] if len(row) > 2 else "[]"
            s_ver = row[3] if len(row) > 3 else "schema-v0.1"
            r_cnt = row[4] if len(row) > 4 else 0
            p_range = row[5] if len(row) > 5 else None
            c_at = row[6] if len(row) > 6 else ""
            st = row[7] if len(row) > 7 else "STAGED"
            p_files_raw = row[8] if len(row) > 8 else "[]"
            m_hash = row[9] if len(row) > 9 else ""

            parsed_files = json.loads(p_files_raw) if p_files_raw else []
            pq_hashes_dict = {}

            if parsed_files:
                for fp in parsed_files:
                    p = Path(fp)
                    if not p.exists() or not p.is_file():
                        raise FileNotFoundError(
                            f"Migration failed: legacy published file missing at {fp}"
                        )
                    pq_hashes_dict[fp] = hashlib.sha256(p.read_bytes()).hexdigest()
            else:
                if st == "PUBLISHED":
                    st = "STAGED"

            p_files = json.dumps(parsed_files)
            pq_hashes = json.dumps(pq_hashes_dict)

            raw_hashes_list = json.loads(raw_h) if raw_h else []
            valid_c_at = c_at if c_at else datetime.now(timezone.utc).isoformat()
            manifest = BatchManifest(
                batch_id=b_id,
                dataset=ds,
                source_raw_hashes=raw_hashes_list,
                schema_version=s_ver,
                record_count=r_cnt,
                partition_date_range=p_range,
                created_at=valid_c_at,
                status=BatchStatus(st),
                published_filepaths=parsed_files,
                parquet_file_hashes=pq_hashes_dict,
            )
            m_hash = manifest.compute_manifest_hash()

            self.conn.execute(
                """
                INSERT INTO batch_manifests (
                    dataset, batch_id, source_raw_hashes, schema_version,
                    record_count, partition_date_range, created_at, status,
                    published_filepaths, parquet_file_hashes, manifest_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    ds,
                    b_id,
                    raw_h,
                    s_ver,
                    r_cnt,
                    p_range,
                    valid_c_at,
                    st,
                    p_files,
                    pq_hashes,
                    m_hash,
                ),
            )
            migrated_count += 1
        return migrated_count

    def register_published_batch(
        self, manifest: BatchManifest, quality_report: Optional[Any] = None
    ) -> None:
        """Atomically register published BatchManifest and optional QualityReport.

        Executed within a single database transaction.

        Raises ValueError if batch status is not PUBLISHED.
        Raises BatchConflictError if batch already exists with conflicting content.
        Raises FileNotFoundError if published files or hashes are missing/corrupted.
        """
        if manifest.status != BatchStatus.PUBLISHED:
            raise ValueError(f"Cannot register batch with non-PUBLISHED status: {manifest.status}")

        for filepath in manifest.published_filepaths:
            p = Path(filepath)
            if not p.exists():
                raise FileNotFoundError(
                    f"Catalog indexing error: Published file does not exist at {p}"
                )
            expected_hash = manifest.parquet_file_hashes.get(
                str(p)
            ) or manifest.parquet_file_hashes.get(p.name)
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
            if existing_hash != manifest.manifest_hash:
                err_msg = (
                    f"Batch '{manifest.batch_id}' in dataset '{manifest.dataset}' "
                    f"already exists with conflicting manifest_hash ({existing_hash})"
                )
                raise BatchConflictError(err_msg)
            if quality_report is None:
                return

        raw_hashes_json = json.dumps(manifest.source_raw_hashes)
        filepaths_json = json.dumps(manifest.published_filepaths)
        parquet_hashes_json = json.dumps(manifest.parquet_file_hashes)

        try:
            self.conn.execute("BEGIN TRANSACTION")
            if not existing:
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

            if quality_report is not None:
                report_json = (
                    quality_report.to_json()
                    if hasattr(quality_report, "to_json")
                    else json.dumps(quality_report)
                )
                b_id = getattr(quality_report, "batch_id", manifest.batch_id)
                ds = getattr(quality_report, "dataset", manifest.dataset)
                overall_passed = getattr(quality_report, "overall_passed", True)
                created_at = getattr(quality_report, "created_at", manifest.created_at)
                summary = getattr(quality_report, "summary", {})
                report_hash = getattr(quality_report, "report_hash", "")
                total_records = summary.get("total_records", manifest.record_count)
                passed_checks = summary.get("passed_checks", 0)
                total_checks = summary.get("total_checks", 0)

                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO quality_reports (
                        dataset, batch_id, overall_passed, created_at,
                        total_records, passed_checks, total_checks, report_hash, report_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        ds,
                        b_id,
                        overall_passed,
                        created_at,
                        total_records,
                        passed_checks,
                        total_checks,
                        report_hash,
                        report_json,
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

    def register_quality_report(self, report: Any) -> None:
        """Register a QualityReport in DuckDB catalog."""
        report_json = report.to_json() if hasattr(report, "to_json") else json.dumps(report)
        batch_id = getattr(report, "batch_id", "")
        dataset = getattr(report, "dataset", "")
        overall_passed = getattr(report, "overall_passed", True)
        created_at = getattr(report, "created_at", "")
        summary = getattr(report, "summary", {})
        report_hash = getattr(report, "report_hash", "")
        total_records = summary.get("total_records", 0)
        passed_checks = summary.get("passed_checks", 0)
        total_checks = summary.get("total_checks", 0)

        self.conn.execute("BEGIN TRANSACTION")
        try:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO quality_reports (
                    dataset, batch_id, overall_passed, created_at,
                    total_records, passed_checks, total_checks, report_hash, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    dataset,
                    batch_id,
                    overall_passed,
                    created_at,
                    total_records,
                    passed_checks,
                    total_checks,
                    report_hash,
                    report_json,
                ),
            )
            self.conn.execute("COMMIT")
        except Exception as e:
            self.conn.execute("ROLLBACK")
            raise e

    def get_quality_report(self, dataset: str, batch_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve QualityReport JSON dictionary for a batch."""
        row = self.conn.execute(
            "SELECT report_json FROM quality_reports WHERE dataset = ? AND batch_id = ?",
            (dataset, batch_id),
        ).fetchone()
        if row:
            return json.loads(row[0])  # type: ignore[no-any-return]
        return None

    def close(self) -> None:
        """Close DuckDB database connection."""
        self.conn.close()
