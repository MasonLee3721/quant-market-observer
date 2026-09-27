"""Atomic Batch Publisher implementation with full provenance validation."""

import hashlib
import logging
import shutil
import uuid
from pathlib import Path
from typing import List, Optional, Sequence

from pydantic import BaseModel

from qmo.storage.catalog import BatchConflictError, DuckDBCatalog
from qmo.storage.manifest import BatchManifest, BatchStatus
from qmo.storage.parquet_store import ParquetStore
from qmo.storage.validation import validate_safe_identifier, validate_sha256_hex

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
          1. Input validation for safety and contract schema consistency.
          2. Full provenance Idempotency & Conflict checking against catalog.
          3. Write models to unique process staging directory.
          4. Validate record count, schema, and SHA-256 integrity.
          5. Atomic directory swap from staging to final normalized directory.
          6. Index manifest in DuckDB catalog.
          7. Process-isolated rollback if catalog or post-swap validation fails.
        """
        validate_safe_identifier(dataset, "dataset")
        validate_safe_identifier(batch_id, "batch_id")
        clean_raw_hashes = [validate_sha256_hex(h, "source_raw_hash") for h in source_raw_hashes]

        if not models:
            raise StorageValidationError("Cannot publish empty batch with zero models")

        # Validate schema_version consistency across models
        for m in models:
            m_ver = getattr(m, "schema_version", None)
            if m_ver != schema_version:
                err_ver = (
                    f"Model schema_version mismatch: model has '{m_ver}', "
                    f"expected '{schema_version}'"
                )
                raise StorageValidationError(err_ver)

        target_dataset_dir = self.normalized_dir / dataset
        target_published_dir = target_dataset_dir / batch_id
        published_file = target_published_dir / "data.parquet"

        # Process-isolated unique staging directory
        run_uuid = uuid.uuid4().hex[:8]
        batch_staging_dir = self.staging_dir / dataset / f"{batch_id}_{run_uuid}"
        staged_file = batch_staging_dir / "data.parquet"

        # Check existing published storage & catalog for Full Provenance Idempotence vs Conflict
        existing_catalog_manifest = self.catalog.get_batch_manifest(dataset, batch_id)
        if target_published_dir.exists() or existing_catalog_manifest is not None:
            if target_published_dir.exists() and published_file.exists():
                actual_pub_hash = hashlib.sha256(published_file.read_bytes()).hexdigest()
                read_pub_rows = ParquetStore.read_record_count(published_file)

                # Write temporary staging Parquet to compute exact staged hash
                staged_temp_hash = ParquetStore.write_models(models, staged_file)
                if batch_staging_dir.exists():
                    shutil.rmtree(batch_staging_dir, ignore_errors=True)

                # Full provenance equality check
                is_hash_match = actual_pub_hash == staged_temp_hash
                is_rows_match = read_pub_rows == len(models)
                cat_hashes = (
                    sorted(existing_catalog_manifest.source_raw_hashes)
                    if existing_catalog_manifest
                    else []
                )
                is_raw_hashes_match = (
                    existing_catalog_manifest is not None
                    and cat_hashes == sorted(clean_raw_hashes)
                )
                is_range_match = (
                    existing_catalog_manifest is None
                    or existing_catalog_manifest.partition_date_range == partition_date_range
                )

                if is_hash_match and is_rows_match and is_raw_hashes_match and is_range_match:
                    # Idempotent re-execution: exact provenance & content match, return manifest
                    if existing_catalog_manifest:
                        return existing_catalog_manifest
                    else:
                        manifest = BatchManifest(
                            batch_id=batch_id,
                            dataset=dataset,
                            source_raw_hashes=clean_raw_hashes,
                            schema_version=schema_version,
                            record_count=len(models),
                            partition_date_range=partition_date_range,
                            status=BatchStatus.PUBLISHED,
                            published_filepaths=[str(published_file)],
                            parquet_file_hashes={str(published_file): actual_pub_hash},
                        )
                        self.catalog.register_published_batch(manifest)
                        return manifest

            # Conflicting batch detected
            err_conflict = (
                f"Batch '{batch_id}' in dataset '{dataset}' "
                "already published with conflicting provenance or content"
            )
            raise BatchConflictError(err_conflict)

        manifest = BatchManifest(
            batch_id=batch_id,
            dataset=dataset,
            source_raw_hashes=clean_raw_hashes,
            schema_version=schema_version,
            record_count=len(models),
            partition_date_range=partition_date_range,
            status=BatchStatus.STAGED,
        )

        staged_hash: Optional[str] = None
        try:
            # 1. Write to Process Staging Directory
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

            # Verify schema fields match model fields
            first_model = models[0]
            expected_fields = list(first_model.model_dump().keys())
            staged_fields = ParquetStore.inspect_schema_names(staged_file)
            for f in expected_fields:
                if f not in staged_fields:
                    raise StorageValidationError(
                        f"Schema field '{f}' missing from staging Parquet file"
                    )

            # 3. Prepare Target & Perform Atomic Directory Swap
            target_dataset_dir.mkdir(parents=True, exist_ok=True)
            batch_staging_dir.replace(target_published_dir)

            # Post-Swap Validation
            if not published_file.exists():
                err_swap = f"Published file missing post-swap at {published_file}"
                raise StorageValidationError(err_swap)

            published_hash = hashlib.sha256(published_file.read_bytes()).hexdigest()
            if published_hash != staged_hash:
                err_digest = (
                    f"SHA-256 mismatch post-swap: expected {staged_hash}, got {published_hash}"
                )
                raise StorageValidationError(err_digest)

            # 4. Mark Manifest PUBLISHED
            manifest.status = BatchStatus.PUBLISHED
            manifest.published_filepaths = [str(published_file)]
            manifest.parquet_file_hashes = {str(published_file): published_hash}
            manifest.manifest_hash = manifest.compute_manifest_hash()

            # 5. Register in DuckDB Catalog AFTER successful atomic swap
            self.catalog.register_published_batch(manifest)

            msg = f"[OK] Published batch '{batch_id}' ({dataset}, {len(models)} rows)"
            logger.info(f"{msg} to {target_published_dir}")
            return manifest

        except Exception as e:
            # Process-isolated Rollback: only delete published directory if it was created
            # by THIS run instance (verified by matching staged_hash)
            if target_published_dir.exists() and published_file.exists() and staged_hash:
                current_pub_hash = hashlib.sha256(published_file.read_bytes()).hexdigest()
                if current_pub_hash == staged_hash:
                    shutil.rmtree(target_published_dir, ignore_errors=True)

            if batch_staging_dir.exists():
                shutil.rmtree(batch_staging_dir, ignore_errors=True)

            manifest.status = BatchStatus.ROLLED_BACK
            logger.error(f"[ROLLBACK] Batch '{batch_id}' failed during publish: {e}")
            err_msg = f"Atomic publish failed for batch '{batch_id}': {e}"
            raise StorageValidationError(err_msg) from e
