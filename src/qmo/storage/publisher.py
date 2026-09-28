"""Atomic Batch Publisher implementation with full provenance validation."""

import hashlib
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from pydantic import BaseModel

from qmo.storage.catalog import BatchConflictError, DuckDBCatalog, StorageValidationError
from qmo.storage.manifest import BatchManifest, BatchStatus
from qmo.storage.parquet_store import ParquetStore
from qmo.storage.validation import validate_safe_identifier, validate_sha256_hex

logger = logging.getLogger(__name__)


class AtomicBatchPublisher:
    """Orchestrates Parquet staging, validation, atomic swap, and catalog indexing."""

    def __init__(
        self,
        root_dir: Path,
        catalog: Optional[DuckDBCatalog] = None,
        validator: Optional[Any] = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.staging_dir = self.root_dir / "staging"
        self.normalized_dir = self.root_dir / "normalized"
        self.catalog = catalog or DuckDBCatalog(self.root_dir / "catalog" / "qmo_catalog.duckdb")
        if validator is False:
            raise ValueError("Quality Gate cannot be disabled (validator cannot be False)")
        if validator is None:
            from qmo.validation.validator import BatchValidator

            self.validator = BatchValidator()
        else:
            self.validator = validator

    def _verify_existing_published_provenance(
        self,
        dataset: str,
        batch_id: str,
        models: Sequence[BaseModel],
        clean_raw_hashes: List[str],
        schema_version: str,
        partition_date_range: Optional[str],
        target_published_dir: Path,
        published_file: Path,
        partition_by_date: bool,
        staged_hash: str,
    ) -> bool:
        """Verify content hash, row count, and provenance against Catalog or Intent file.

        Fails closed (returns False) if neither Catalog Manifest nor a single valid
        Intent Marker exists, or if any metadata (raw hashes, schema version, record count,
        date range, content hash) mismatches.
        """
        pub_files = (
            sorted(p for p in target_published_dir.glob("**/*.parquet") if p.is_file())
            if partition_by_date
            else ([published_file] if published_file.exists() else [])
        )
        if not pub_files:
            return False

        actual_pub_hash = (
            hashlib.sha256(
                "".join(hashlib.sha256(pf.read_bytes()).hexdigest() for pf in pub_files).encode(
                    "utf-8"
                )
            ).hexdigest()
            if partition_by_date
            else hashlib.sha256(published_file.read_bytes()).hexdigest()
        )
        if actual_pub_hash != staged_hash:
            return False

        read_pub_rows = sum(ParquetStore.read_record_count(pf) for pf in pub_files)
        if read_pub_rows != len(models):
            return False

        cat_manifest = self.catalog.get_batch_manifest(dataset, batch_id)
        if cat_manifest is not None:
            if sorted(cat_manifest.source_raw_hashes) != sorted(clean_raw_hashes):
                return False
            if cat_manifest.schema_version != schema_version:
                return False
            if cat_manifest.record_count != len(models):
                return False
            if cat_manifest.partition_date_range != partition_date_range:
                return False

            # Verify integrity of all published files listed in cat_manifest
            for fp in cat_manifest.published_filepaths:
                p = Path(fp)
                if not p.exists():
                    return False
                expected_h = cat_manifest.parquet_file_hashes.get(
                    str(p)
                ) or cat_manifest.parquet_file_hashes.get(p.name)
                if expected_h:
                    actual_h = hashlib.sha256(p.read_bytes()).hexdigest()
                    if actual_h != expected_h:
                        return False
            return True

        # FAIL CLOSED: Require exactly one valid Intent marker file if Catalog manifest is absent
        intent_files = sorted(target_published_dir.glob(".intent_*.json"))
        if len(intent_files) != 1:
            return False

        try:
            intent_data = json.loads(intent_files[0].read_text())
            if intent_data.get("dataset") != dataset:
                return False
            if intent_data.get("batch_id") != batch_id:
                return False
            if intent_data.get("source_raw_hashes") != sorted(clean_raw_hashes):
                return False
            if intent_data.get("schema_version") != schema_version:
                return False
            if intent_data.get("record_count") != len(models):
                return False
            if intent_data.get("partition_date_range") != partition_date_range:
                return False
            if intent_data.get("staged_hash") != staged_hash:
                return False
            return True
        except Exception:
            return False

    def _create_and_register_manifest(
        self,
        batch_id: str,
        dataset: str,
        clean_raw_hashes: List[str],
        schema_version: str,
        record_count: int,
        partition_date_range: Optional[str],
        target_published_dir: Path,
        published_file: Path,
        partition_by_date: bool,
        quality_report: Optional[Any] = None,
    ) -> BatchManifest:
        """Create BatchManifest including parquet/report hashes and register catalog atomically."""
        created_target_files: List[Path] = []
        if quality_report is not None:
            qr_json = target_published_dir / "quality_report.json"
            qr_md = target_published_dir / "quality_report.md"
            existed_json = qr_json.exists()
            existed_md = qr_md.exists()

            if not existed_json or not existed_md:
                staged_qr_dir = (
                    self.staging_dir / dataset / f".qr_stage_{uuid.uuid4().hex}"
                )
                staged_qr_dir.mkdir(parents=True, exist_ok=True)
                try:
                    staged_json = staged_qr_dir / "quality_report.json"
                    staged_md = staged_qr_dir / "quality_report.md"

                    if not existed_json:
                        staged_json.write_text(quality_report.to_json())
                        from qmo.validation.models import QualityReport

                        QualityReport.model_validate_json(staged_json.read_text())

                    if not existed_md:
                        staged_md.write_text(quality_report.to_markdown())

                    if not existed_json:
                        tmp_target_json = (
                            target_published_dir / ".quality_report.json.tmp"
                        )
                        shutil.copy2(staged_json, tmp_target_json)
                        created_target_files.append(tmp_target_json)
                        os.replace(tmp_target_json, qr_json)
                        created_target_files.remove(tmp_target_json)
                        created_target_files.append(qr_json)

                    if not existed_md:
                        tmp_target_md = (
                            target_published_dir / ".quality_report.md.tmp"
                        )
                        shutil.copy2(staged_md, tmp_target_md)
                        created_target_files.append(tmp_target_md)
                        os.replace(tmp_target_md, qr_md)
                        created_target_files.remove(tmp_target_md)
                        created_target_files.append(qr_md)
                except Exception as e:
                    for f in created_target_files:
                        if f.exists():
                            try:
                                f.unlink()
                            except Exception:
                                pass
                    raise StorageValidationError(
                        f"Failed to persist QualityReport to published directory: {e}"
                    ) from e
                finally:
                    if staged_qr_dir.exists():
                        shutil.rmtree(staged_qr_dir, ignore_errors=True)

        pub_files = (
            sorted(p for p in target_published_dir.glob("**/*.parquet") if p.is_file())
            if partition_by_date
            else ([published_file] if published_file.exists() else [])
        )
        all_pub_files = list(pub_files)
        for r_name in ("quality_report.json", "quality_report.md"):
            r_path = target_published_dir / r_name
            if r_path.exists():
                all_pub_files.append(r_path)

        pub_paths = [str(p) for p in all_pub_files]
        pq_hashes = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in all_pub_files
        }

        manifest = BatchManifest(
            batch_id=batch_id,
            dataset=dataset,
            source_raw_hashes=clean_raw_hashes,
            schema_version=schema_version,
            record_count=record_count,
            partition_date_range=partition_date_range,
            status=BatchStatus.PUBLISHED,
            published_filepaths=pub_paths,
            parquet_file_hashes=pq_hashes,
        )

        if quality_report is None:
            qr_path = target_published_dir / "quality_report.json"
            if qr_path.exists():
                try:
                    from qmo.validation.models import QualityReport

                    quality_report = QualityReport.model_validate_json(qr_path.read_text())
                except Exception as e:
                    raise StorageValidationError(
                        f"Corrupted or invalid quality_report.json in published directory: {e}"
                    ) from e

        try:
            if quality_report is not None:
                self.catalog.register_published_batch(manifest, quality_report=quality_report)
            else:
                self.catalog.register_published_batch(manifest)
        except Exception:
            for f in created_target_files:
                if f.exists():
                    try:
                        f.unlink()
                    except Exception:
                        pass
            raise
        return manifest

    def publish_batch(
        self,
        batch_id: str,
        dataset: str,
        models: Sequence[BaseModel],
        source_raw_hashes: List[str],
        schema_version: str = "schema-v0.1",
        partition_date_range: Optional[str] = None,
        partition_by_date: bool = False,
        target_tickers: Optional[Sequence[str]] = None,
        expected_date_range: Optional[str] = None,
        twse_envelope: Optional[Any] = None,
        tpex_envelope: Optional[Any] = None,
        _pre_swap_hook: Optional[Callable[[], None]] = None,
    ) -> BatchManifest:
        """Execute atomic publish workflow for a normalized model batch."""
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

        quality_report = None
        # Execute Quality Gate validation if a validator is configured
        if self.validator is not None:
            quality_report = self.validator.validate_batch(
                batch_id=batch_id,
                dataset=dataset,
                models=models,
                schema_version=schema_version,
                target_tickers=target_tickers,
                expected_date_range=expected_date_range,
                twse_envelope=twse_envelope,
                tpex_envelope=tpex_envelope,
                raise_on_failure=True,
            )

        target_dataset_dir = self.normalized_dir / dataset
        target_published_dir = target_dataset_dir / batch_id
        published_file = target_published_dir / "data.parquet"

        # Process-isolated unique staging directory and ownership marker
        run_uuid = uuid.uuid4().hex
        owner_marker_name = f".owner_{run_uuid}"
        batch_staging_dir = self.staging_dir / dataset / f"{batch_id}_{run_uuid}"
        staged_file = (
            batch_staging_dir / "partitioned"
            if partition_by_date
            else batch_staging_dir / "data.parquet"
        )

        # Check existing published storage & catalog for Full Provenance Idempotence vs Conflict
        existing_catalog_manifest = self.catalog.get_batch_manifest(dataset, batch_id)
        if target_published_dir.exists() or existing_catalog_manifest is not None:
            if target_published_dir.exists():
                part_cols = ["trade_date"] if partition_by_date else None
                staged_temp_hash = ParquetStore.write_models(
                    models, staged_file, partition_cols=part_cols
                )
                if batch_staging_dir.exists():
                    shutil.rmtree(batch_staging_dir, ignore_errors=True)

                if self._verify_existing_published_provenance(
                    dataset=dataset,
                    batch_id=batch_id,
                    models=models,
                    clean_raw_hashes=clean_raw_hashes,
                    schema_version=schema_version,
                    partition_date_range=partition_date_range,
                    target_published_dir=target_published_dir,
                    published_file=published_file,
                    partition_by_date=partition_by_date,
                    staged_hash=staged_temp_hash,
                ):
                    if existing_catalog_manifest is not None:
                        return existing_catalog_manifest
                    else:
                        return self._create_and_register_manifest(
                            batch_id=batch_id,
                            dataset=dataset,
                            clean_raw_hashes=clean_raw_hashes,
                            schema_version=schema_version,
                            record_count=len(models),
                            partition_date_range=partition_date_range,
                            target_published_dir=target_published_dir,
                            published_file=published_file,
                            partition_by_date=partition_by_date,
                            quality_report=quality_report,
                        )

            err_conflict = (
                f"Batch '{batch_id}' in dataset '{dataset}' "
                "already published with conflicting provenance or content"
            )
            raise BatchConflictError(err_conflict)

        staged_hash: Optional[str] = None
        try:
            # 1. Write to Process Staging Directory
            part_cols = ["trade_date"] if partition_by_date else None
            staged_hash = ParquetStore.write_models(models, staged_file, partition_cols=part_cols)

            # 2. Staging Validation
            if not staged_file.exists():
                raise StorageValidationError(f"Staged path missing at {staged_file}")

            read_rows = ParquetStore.read_record_count(staged_file)
            if read_rows != len(models):
                raise StorageValidationError(
                    f"Row count mismatch in staging: wrote {len(models)}, read {read_rows}"
                )

            first_model = models[0]
            try:
                ParquetStore.verify_schema_contract(
                    staged_file, type(first_model), partition_cols=part_cols
                )
            except ValueError as e:
                raise StorageValidationError(
                    f"Staging schema contract verification failed: {e}"
                ) from e

            # Write process ownership & intent markers into staging before rename
            owner_marker_file = batch_staging_dir / owner_marker_name
            owner_marker_file.write_text(run_uuid)

            intent_marker_name = f".intent_{run_uuid}.json"
            intent_marker_file = batch_staging_dir / intent_marker_name
            intent_payload = {
                "dataset": dataset,
                "batch_id": batch_id,
                "source_raw_hashes": sorted(clean_raw_hashes),
                "schema_version": schema_version,
                "record_count": len(models),
                "partition_date_range": partition_date_range,
                "staged_hash": staged_hash,
            }
            intent_marker_file.write_text(json.dumps(intent_payload))

            # Write QualityReport artifacts into staging before swap if available
            if quality_report is not None:
                try:
                    (batch_staging_dir / "quality_report.json").write_text(quality_report.to_json())
                    (batch_staging_dir / "quality_report.md").write_text(
                        quality_report.to_markdown()
                    )
                except Exception as e:
                    raise StorageValidationError(
                        f"Failed to persist QualityReport to staging: {e}"
                    ) from e

            # Controlled hook execution right before atomic swap
            if _pre_swap_hook is not None:
                _pre_swap_hook()

            # 3. Prepare Target & Perform Atomic Directory Swap
            target_dataset_dir.mkdir(parents=True, exist_ok=True)
            if target_published_dir.exists():
                if self._verify_existing_published_provenance(
                    dataset=dataset,
                    batch_id=batch_id,
                    models=models,
                    clean_raw_hashes=clean_raw_hashes,
                    schema_version=schema_version,
                    partition_date_range=partition_date_range,
                    target_published_dir=target_published_dir,
                    published_file=published_file,
                    partition_by_date=partition_by_date,
                    staged_hash=staged_hash,
                ):
                    if batch_staging_dir.exists():
                        shutil.rmtree(batch_staging_dir, ignore_errors=True)
                    cat_man = self.catalog.get_batch_manifest(dataset, batch_id)
                    if cat_man is not None:
                        return cat_man

                    return self._create_and_register_manifest(
                        batch_id=batch_id,
                        dataset=dataset,
                        clean_raw_hashes=clean_raw_hashes,
                        schema_version=schema_version,
                        record_count=len(models),
                        partition_date_range=partition_date_range,
                        target_published_dir=target_published_dir,
                        published_file=published_file,
                        partition_by_date=partition_by_date,
                        quality_report=quality_report,
                    )

                if batch_staging_dir.exists():
                    shutil.rmtree(batch_staging_dir, ignore_errors=True)
                err_conc = (
                    f"Batch '{batch_id}' in dataset '{dataset}' "
                    "published concurrently with conflicting provenance or content"
                )
                raise BatchConflictError(err_conc)

            try:
                batch_staging_dir.replace(target_published_dir)
            except OSError as err:
                if target_published_dir.exists():
                    if self._verify_existing_published_provenance(
                        dataset=dataset,
                        batch_id=batch_id,
                        models=models,
                        clean_raw_hashes=clean_raw_hashes,
                        schema_version=schema_version,
                        partition_date_range=partition_date_range,
                        target_published_dir=target_published_dir,
                        published_file=published_file,
                        partition_by_date=partition_by_date,
                        staged_hash=staged_hash,
                    ):
                        if batch_staging_dir.exists():
                            shutil.rmtree(batch_staging_dir, ignore_errors=True)
                        cat_man = self.catalog.get_batch_manifest(dataset, batch_id)
                        if cat_man is not None:
                            return cat_man

                        return self._create_and_register_manifest(
                            batch_id=batch_id,
                            dataset=dataset,
                            clean_raw_hashes=clean_raw_hashes,
                            schema_version=schema_version,
                            record_count=len(models),
                            partition_date_range=partition_date_range,
                            target_published_dir=target_published_dir,
                            published_file=published_file,
                            partition_by_date=partition_by_date,
                            quality_report=quality_report,
                        )

                    if batch_staging_dir.exists():
                        shutil.rmtree(batch_staging_dir, ignore_errors=True)
                    err_conc = (
                        f"Batch '{batch_id}' in dataset '{dataset}' "
                        "published concurrently with conflicting provenance or content"
                    )
                    raise BatchConflictError(err_conc) from err
                else:
                    batch_staging_dir.replace(target_published_dir)

            # Post-Swap Validation
            pub_files = (
                sorted(p for p in target_published_dir.glob("**/*.parquet") if p.is_file())
                if partition_by_date
                else [published_file]
            )
            if not pub_files or not all(p.exists() for p in pub_files):
                err_swap = f"Published file(s) missing post-swap at {target_published_dir}"
                raise StorageValidationError(err_swap)

            published_hash = (
                hashlib.sha256(
                    "".join(hashlib.sha256(pf.read_bytes()).hexdigest() for pf in pub_files).encode(
                        "utf-8"
                    )
                ).hexdigest()
                if partition_by_date
                else hashlib.sha256(published_file.read_bytes()).hexdigest()
            )
            if published_hash != staged_hash:
                err_digest = (
                    f"SHA-256 mismatch post-swap: expected {staged_hash}, got {published_hash}"
                )
                raise StorageValidationError(err_digest)

            manifest = self._create_and_register_manifest(
                batch_id=batch_id,
                dataset=dataset,
                clean_raw_hashes=clean_raw_hashes,
                schema_version=schema_version,
                record_count=len(models),
                partition_date_range=partition_date_range,
                target_published_dir=target_published_dir,
                published_file=published_file,
                partition_by_date=partition_by_date,
                quality_report=quality_report,
            )

            # Cleanup ownership & intent markers on successful publish
            target_owner_file = target_published_dir / owner_marker_name
            if target_owner_file.exists():
                target_owner_file.unlink(missing_ok=True)
            target_intent_file = target_published_dir / intent_marker_name
            if target_intent_file.exists():
                target_intent_file.unlink(missing_ok=True)

            msg = f"[OK] Published batch '{batch_id}' ({dataset}, {len(models)} rows)"
            logger.info(f"{msg} to {target_published_dir}")
            return manifest

        except Exception as e:
            # Process-isolated Rollback: ONLY delete target_published_dir if it contains
            # THIS process instance's owner marker file AND catalog has no published manifest!
            target_owner_file = target_published_dir / owner_marker_name
            target_intent_file = target_published_dir / intent_marker_name
            cat_manifest = self.catalog.get_batch_manifest(dataset, batch_id)
            if target_published_dir.exists() and target_owner_file.exists():
                if cat_manifest is None:
                    shutil.rmtree(target_published_dir, ignore_errors=True)
                else:
                    target_owner_file.unlink(missing_ok=True)
                    target_intent_file.unlink(missing_ok=True)

            if batch_staging_dir.exists():
                shutil.rmtree(batch_staging_dir, ignore_errors=True)

            if isinstance(e, BatchConflictError):
                raise

            logger.error(f"[ROLLBACK] Batch '{batch_id}' failed during publish: {e}")
            err_msg = f"Atomic publish failed for batch '{batch_id}': {e}"
            raise StorageValidationError(err_msg) from e
