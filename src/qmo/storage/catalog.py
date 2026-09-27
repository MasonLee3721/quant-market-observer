"""DuckDB Catalog Metadata Indexer implementation."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

from qmo.storage.manifest import BatchManifest, BatchStatus


class DuckDBCatalog:
    """Indexed metadata catalog powered by DuckDB for published batches."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is not None:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = duckdb.connect(str(self.db_path))
        else:
            self.conn = duckdb.connect(":memory:")

        self._init_schema()

    def _init_schema(self) -> None:
        """Create catalog metadata tables if they do not exist."""
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_manifests (
                batch_id VARCHAR PRIMARY KEY,
                dataset VARCHAR NOT NULL,
                source_raw_hashes VARCHAR NOT NULL,
                schema_version VARCHAR NOT NULL,
                record_count BIGINT NOT NULL,
                partition_date_range VARCHAR,
                created_at VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                published_filepaths VARCHAR NOT NULL,
                manifest_hash VARCHAR NOT NULL
            );
            """
        )

    def register_published_batch(self, manifest: BatchManifest) -> None:
        """Register a successfully published batch manifest in DuckDB catalog.

        Raises ValueError if batch status is not PUBLISHED or if files do not exist.
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

        raw_hashes_json = json.dumps(manifest.source_raw_hashes)
        filepaths_json = json.dumps(manifest.published_filepaths)

        self.conn.execute(
            """
            INSERT OR REPLACE INTO batch_manifests (
                batch_id, dataset, source_raw_hashes, schema_version,
                record_count, partition_date_range, created_at, status,
                published_filepaths, manifest_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                manifest.batch_id,
                manifest.dataset,
                raw_hashes_json,
                manifest.schema_version,
                manifest.record_count,
                manifest.partition_date_range,
                manifest.created_at,
                manifest.status.value,
                filepaths_json,
                manifest.manifest_hash,
            ),
        )

    def get_batch_manifest(self, batch_id: str) -> Optional[BatchManifest]:
        """Fetch batch manifest from DuckDB catalog by batch_id."""
        rel = self.conn.execute(
            "SELECT * FROM batch_manifests WHERE batch_id = ?", (batch_id,)
        ).fetchall()
        if not rel:
            return None

        row = rel[0]
        return BatchManifest(
            batch_id=row[0],
            dataset=row[1],
            source_raw_hashes=json.loads(row[2]),
            schema_version=row[3],
            record_count=row[4],
            partition_date_range=row[5],
            created_at=row[6],
            status=BatchStatus(row[7]),
            published_filepaths=json.loads(row[8]),
            manifest_hash=row[9],
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
                    "batch_id": r[0],
                    "dataset": r[1],
                    "source_raw_hashes": json.loads(r[2]),
                    "schema_version": r[3],
                    "record_count": r[4],
                    "partition_date_range": r[5],
                    "created_at": r[6],
                    "status": r[7],
                    "published_filepaths": json.loads(r[8]),
                    "manifest_hash": r[9],
                }
            )
        return results

    def close(self) -> None:
        """Close DuckDB database connection."""
        self.conn.close()
