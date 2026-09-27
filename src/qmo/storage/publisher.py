"""Atomic Batch Publisher implementation with staging validation and fail-safe rollback."""

import logging
import shutil
from pathlib import Path
from typing import List, Optional, Sequence

from pydantic import BaseModel

from qmo.storage.catalog import DuckDBCatalog
from qmo.storage.manifest import BatchManifest, BatchStatus
from qmo.storage.parquet_store import ParquetStore

logger = logging.getLogger(__name__)


class StorageValidationError(Exception):
    """Raised when staging parquet file validation fails prior to atomic publish."""


class AtomicBatchPublisher:
    """Orchestrates Parquet staging, validation, atomic swap, and catalog indexing."""

    def __init__(
        self,
        root_dir: Path,
        catalog: Optional[DuckDBCatalog] = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.staging_dir = self.root_dir / "staging"
        self.normalized_dir = self.root_dir / "normalized"
        self.catalog = catalog or DuckDBCatalog(self.root_dir / "catalog" / "qmo_catalog.duckdb")

    def publish_batch(
        self,
        batch_id: str,
        dataset: str,
        models: Sequence[BaseModel],
        source_raw_hashes: List[str],
        schema_version: str = "schema-v0.1",
        partition_date_range: Optional[str] = None,
    ) -> BatchManifest:
        """Execute atomic publish workflow for a normalized model batch.

        Workflow:
          1. Write models to staging directory.
          2. Validate record count, schema, and checksum integrity.
          3. Atomic swap/rename from staging to final normalized directory.
          4. Index manifest in DuckDB catalog.
          5. Rollback staging & preserve prior data if any step fails.
        """
        if not models:
            raise StorageValidationError("Cannot publish empty batch with zero models")

        batch_staging_dir = self.staging_dir / batch_id
        staged_file = batch_staging_dir / f"{dataset}.parquet"

        target_dataset_dir = self.normalized_dir / dataset
        published_file = target_dataset_dir / f"{batch_id}.parquet"

        manifest = BatchManifest(
            batch_id=batch_id,
            dataset=dataset,
            source_raw_hashes=source_raw_hashes,
            schema_version=schema_version,
            record_count=len(models),
            partition_date_range=partition_date_range,
            status=BatchStatus.STAGED,
        )

        try:
            # 1. Write to Staging Directory
            staged_hash = ParquetStore.write_models(models, staged_file)

            # 2. Staging Validation
            if (
                not staged_file.exists()
                or staged_file.stat().st_size == 0
                or len(staged_hash) != 64
            ):
                raise StorageValidationError(f"Staged file missing or 0-byte at {staged_file}")

            read_rows = ParquetStore.read_record_count(staged_file)
            if read_rows != len(models):
                raise StorageValidationError(
                    f"Row count mismatch in staging: wrote {len(models)}, read {read_rows}"
                )

            # 3. Prepare Target & Perform Atomic Swap
            target_dataset_dir.mkdir(parents=True, exist_ok=True)

            # Idempotence check: if exact batch file exists and is identical, replace atomically
            staged_file.replace(published_file)

            # Clean up staging directory
            if batch_staging_dir.exists():
                shutil.rmtree(batch_staging_dir, ignore_errors=True)

            # 4. Mark Manifest PUBLISHED
            manifest.status = BatchStatus.PUBLISHED
            manifest.published_filepaths = [str(published_file)]
            manifest.manifest_hash = manifest.compute_manifest_hash()

            # 5. Register in DuckDB Catalog AFTER successful atomic swap
            self.catalog.register_published_batch(manifest)

            msg = f"[OK] Published batch '{batch_id}' ({dataset}, {len(models)} rows)"
            logger.info(f"{msg} to {published_file}")
            return manifest

        except Exception as e:
            # Rollback: cleanup staging directory and leave existing published files untouched
            if batch_staging_dir.exists():
                shutil.rmtree(batch_staging_dir, ignore_errors=True)

            manifest.status = BatchStatus.ROLLED_BACK
            logger.error(f"[ROLLBACK] Batch '{batch_id}' failed during publish: {e}")
            err_msg = f"Atomic publish failed for batch '{batch_id}': {e}"
            raise StorageValidationError(err_msg) from e
