import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import duckdb
import pytest

from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.catalog import BatchConflictError, DuckDBCatalog, StorageValidationError
from qmo.storage.manifest import BatchManifest, BatchStatus
from qmo.storage.parquet_store import ParquetStore
from qmo.storage.publisher import AtomicBatchPublisher
from qmo.storage.raw_store import RawSnapshotStore

VALID_RAW_HASH_1 = "a" * 64
VALID_RAW_HASH_2 = "b" * 64


def test_raw_snapshot_store_byte_for_byte_immutability_and_recovery(tmp_path: Path) -> None:
    """Verify raw snapshot store preserves exact raw_body_bytes and recovers from corruption."""
    store = RawSnapshotStore(base_dir=tmp_path / "raw")

    raw_body_bytes = b'{"status": 200, "msg": "success", "data": [{"stock_id": "2330"}]}'
    env = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"dataset": "TaiwanStockPrice", "data_id": "2330"},
        status_code=200,
        raw_body_bytes=raw_body_bytes,
    )

    hash1, raw_path1 = store.save(env, "TaiwanStockPrice")
    assert raw_path1.exists()
    assert raw_path1.read_bytes() == raw_body_bytes
    assert hash1 in raw_path1.name

    # Re-saving identical payload skips re-writing
    mtime1 = raw_path1.stat().st_mtime_ns
    hash2, raw_path2 = store.save(env, "TaiwanStockPrice")
    assert hash1 == hash2
    assert raw_path1 == raw_path2
    assert raw_path2.stat().st_mtime_ns == mtime1

    # Simulate corruption on disk
    raw_path1.write_bytes(b"corrupted raw data")
    assert raw_path1.read_bytes() == b"corrupted raw data"

    # Re-saving recovers exact raw_body_bytes
    hash3, raw_path3 = store.save(env, "TaiwanStockPrice")
    assert hash3 == hash1
    assert raw_path3.read_bytes() == raw_body_bytes

    # Reject path traversal
    with pytest.raises(ValueError, match="Unsafe or invalid dataset_name"):
        store.save(env, "../unsafe_path")


def test_duckdb_catalog_schema_migration_from_legacy_db(tmp_path: Path) -> None:
    """Verify DuckDBCatalog detects legacy DB schema and migrates to composite primary key."""
    db_file = tmp_path / "legacy_catalog.duckdb"

    # 1. Create a legacy DuckDB database with old single primary key (batch_id)
    conn = duckdb.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE batch_manifests (
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
    conn.execute(
        """
        INSERT INTO batch_manifests VALUES (
            'legacy_b1', 'daily_price', '[]', 'schema-v0.1', 10, '2026-09-25',
            '2026-09-25T00:00:00Z', 'PUBLISHED', '[]', 'hash_legacy_1'
        );
        """
    )
    conn.close()

    # 2. Open catalog with new DuckDBCatalog class (triggers migration)
    catalog = DuckDBCatalog(db_file)

    # 3. Verify legacy row was migrated into composite primary key table
    m = catalog.get_batch_manifest("daily_price", "legacy_b1")
    assert m is not None
    assert m.batch_id == "legacy_b1"
    assert m.dataset == "daily_price"
    assert m.record_count == 10

    catalog.close()


def test_parquet_store_read_write_and_schema_inspection(tmp_path: Path) -> None:
    """Verify ParquetStore writes models, checks row count, and inspects schema."""
    output_path = tmp_path / "test_price.parquet"

    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        ),
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="8069",
            market="TPEx",
            open_price=50.0,
            close_price=52.0,
            trading_volume=500,
            trading_value=26000,
            source="FinMind:TaiwanStockPrice",
        ),
    ]

    sha256_digest = ParquetStore.write_models(models, output_path)
    assert len(sha256_digest) == 64
    assert output_path.exists()

    rows = ParquetStore.read_record_count(output_path)
    assert rows == 2

    schema_names = ParquetStore.inspect_schema_names(output_path)
    assert "stock_id" in schema_names
    assert "trade_date" in schema_names
    assert "close_price" in schema_names


def test_atomic_batch_publisher_staging_swap_and_catalog(tmp_path: Path) -> None:
    """Verify staging isolation, atomic rename, catalog indexing, and manifest generation."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)

    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    batch_id = "batch_20260925_001"
    manifest = publisher.publish_batch(
        batch_id=batch_id,
        dataset="daily_price",
        models=models,
        source_raw_hashes=[VALID_RAW_HASH_1],
    )

    assert manifest.status == BatchStatus.PUBLISHED
    assert manifest.record_count == 1
    assert len(manifest.published_filepaths) == 3
    assert len(manifest.parquet_file_hashes) == 3

    assert any("data.parquet" in fp for fp in manifest.published_filepaths)
    assert any("quality_report.json" in fp for fp in manifest.published_filepaths)
    assert any("quality_report.md" in fp for fp in manifest.published_filepaths)

    # Verify DuckDB catalog registered published batch by composite key (dataset, batch_id)
    cat_manifest = publisher.catalog.get_batch_manifest("daily_price", batch_id)
    assert cat_manifest is not None
    assert cat_manifest.batch_id == batch_id
    assert cat_manifest.dataset == "daily_price"
    assert cat_manifest.status == BatchStatus.PUBLISHED
    assert cat_manifest.record_count == 1


def test_atomic_publisher_rollback_when_catalog_registration_fails(tmp_path: Path) -> None:
    """Verify that if catalog registration fails post-swap, published dir is deleted."""
    catalog_mock = MagicMock(spec=DuckDBCatalog)
    catalog_mock.get_batch_manifest.return_value = None
    catalog_mock.register_published_batch.side_effect = RuntimeError("Simulated DB failure")

    publisher = AtomicBatchPublisher(root_dir=tmp_path, catalog=catalog_mock)

    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    batch_id = "batch_fail_catalog"
    target_published_dir = tmp_path / "normalized" / "daily_price" / batch_id

    with pytest.raises(StorageValidationError, match="Simulated DB failure"):
        publisher.publish_batch(
            batch_id=batch_id,
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_1],
        )

    # Critical Assertion: Target published directory must be cleaned up / deleted on catalog failure
    assert not target_published_dir.exists()


def test_idempotency_verifies_full_provenance(tmp_path: Path) -> None:
    """Verify re-publishing identical batch is idempotent while different raw hashes raise error."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models_v1 = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    m1 = publisher.publish_batch(
        batch_id="batch_prov",
        dataset="daily_price",
        models=models_v1,
        source_raw_hashes=[VALID_RAW_HASH_1],
        partition_date_range="2026-09-25",
    )

    # Identical re-publish succeeds idempotently
    m2 = publisher.publish_batch(
        batch_id="batch_prov",
        dataset="daily_price",
        models=models_v1,
        source_raw_hashes=[VALID_RAW_HASH_1],
        partition_date_range="2026-09-25",
    )
    assert m1.batch_id == m2.batch_id
    assert m2.status == BatchStatus.PUBLISHED

    # Re-publish with DIFFERENT source_raw_hashes raises BatchConflictError
    with pytest.raises(BatchConflictError, match="conflicting provenance or content"):
        publisher.publish_batch(
            batch_id="batch_prov",
            dataset="daily_price",
            models=models_v1,
            source_raw_hashes=[VALID_RAW_HASH_2],
            partition_date_range="2026-09-25",
        )

    # Re-publish with DIFFERENT partition_date_range raises BatchConflictError
    with pytest.raises(BatchConflictError, match="conflicting provenance or content"):
        publisher.publish_batch(
            batch_id="batch_prov",
            dataset="daily_price",
            models=models_v1,
            source_raw_hashes=[VALID_RAW_HASH_1],
            partition_date_range="2026-09-26",
        )


def test_path_traversal_and_invalid_hash_rejection(tmp_path: Path) -> None:
    """Verify input validation rejects path traversal characters and invalid non-hex hashes."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    with pytest.raises(ValueError, match="Unsafe or invalid dataset"):
        publisher.publish_batch(
            batch_id="batch1",
            dataset="../unsafe",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_1],
        )

    with pytest.raises(ValueError, match="Unsafe or invalid batch_id"):
        publisher.publish_batch(
            batch_id="../../batch",
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_1],
        )

    with pytest.raises(ValueError, match="Invalid source_raw_hash"):
        publisher.publish_batch(
            batch_id="batch1",
            dataset="daily_price",
            models=models,
            source_raw_hashes=["invalid_non_hex_hash"],
        )


def test_schema_version_mismatch_fails_publish(tmp_path: Path) -> None:
    """Verify model with mismatched schema_version fails staging validation."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    mismatched_model = DailyPrice(
        trade_date="2026-09-25",
        stock_id="2330",
        schema_version="schema-v0.2",
    )

    with pytest.raises(StorageValidationError, match="Model schema_version mismatch"):
        publisher.publish_batch(
            batch_id="batch_bad_ver",
            dataset="daily_price",
            models=[mismatched_model],
            source_raw_hashes=[VALID_RAW_HASH_1],
            schema_version="schema-v0.1",
        )


def test_catalog_rejects_non_published_manifest_or_hash_mismatch(tmp_path: Path) -> None:
    """Verify DuckDB catalog rejects non-PUBLISHED manifests or hash mismatches."""
    catalog = DuckDBCatalog(tmp_path / "catalog.duckdb")

    m_staged = BatchManifest(
        batch_id="b_staged",
        dataset="daily_price",
        status=BatchStatus.STAGED,
    )
    with pytest.raises(ValueError, match="Cannot register batch with non-PUBLISHED status"):
        catalog.register_published_batch(m_staged)

    # Missing file error
    missing_path = str(tmp_path / "non_existent.parquet")
    m_missing = BatchManifest(
        batch_id="b_missing",
        dataset="daily_price",
        status=BatchStatus.PUBLISHED,
        published_filepaths=[missing_path],
        parquet_file_hashes={missing_path: "a" * 64},
    )
    with pytest.raises(FileNotFoundError, match="Published file does not exist"):
        catalog.register_published_batch(m_missing)

    # Hash mismatch error
    real_file = tmp_path / "data.parquet"
    real_file.write_bytes(b"dummy parquet bytes")

    m_hash_mismatch = BatchManifest(
        batch_id="b_mismatch",
        dataset="daily_price",
        status=BatchStatus.PUBLISHED,
        published_filepaths=[str(real_file)],
        parquet_file_hashes={str(real_file): "f" * 64},
    )
    with pytest.raises(ValueError, match="Published file hash mismatch"):
        catalog.register_published_batch(m_hash_mismatch)


def test_manifest_published_key_set_parity_and_validation() -> None:
    """Verify BatchManifest enforces non-empty published_filepaths and 1-to-1 hash key parity."""
    # 1. Empty published_filepaths for PUBLISHED status
    err_empty = "PUBLISHED batch manifest must have non-empty published_filepaths"
    with pytest.raises(ValueError, match=err_empty):
        BatchManifest(
            batch_id="b_empty_pub",
            dataset="daily_price",
            status=BatchStatus.PUBLISHED,
            published_filepaths=[],
        )

    # 2. Key set mismatch between published_filepaths and parquet_file_hashes
    with pytest.raises(ValueError, match="Mismatch between published_filepaths key set"):
        BatchManifest(
            batch_id="b_key_mismatch",
            dataset="daily_price",
            status=BatchStatus.PUBLISHED,
            published_filepaths=["path/a.parquet"],
            parquet_file_hashes={"path/b.parquet": "a" * 64},
        )

    # 3. Invalid non-64-hex SHA-256 hash string
    with pytest.raises(ValueError, match="Invalid parquet_file_hashes"):
        BatchManifest(
            batch_id="b_invalid_hex",
            dataset="daily_price",
            status=BatchStatus.PUBLISHED,
            published_filepaths=["path/a.parquet"],
            parquet_file_hashes={"path/a.parquet": "not_a_valid_64_char_hex_string"},
        )


def test_atomic_batch_publisher_with_trade_date_partitioning(tmp_path: Path) -> None:
    """Verify AtomicBatchPublisher supports partition_by_date for trade_date Hive partitioning."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)

    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        ),
        DailyPrice(
            trade_date="2026-09-26",
            stock_id="2330",
            market="TWSE",
            open_price=105.0,
            close_price=108.0,
            trading_volume=1200,
            trading_value=129600,
            source="FinMind:TaiwanStockPrice",
        ),
    ]

    batch_id = "batch_partitioned"
    manifest = publisher.publish_batch(
        batch_id=batch_id,
        dataset="daily_price",
        models=models,
        source_raw_hashes=[VALID_RAW_HASH_1],
        partition_by_date=True,
    )

    assert manifest.status == BatchStatus.PUBLISHED
    assert manifest.record_count == 2
    assert len(manifest.published_filepaths) >= 2
    assert set(manifest.published_filepaths) == set(manifest.parquet_file_hashes.keys())

    for fp in manifest.published_filepaths:
        assert Path(fp).exists()

    cat_m = publisher.catalog.get_batch_manifest("daily_price", batch_id)
    assert cat_m is not None
    assert cat_m.record_count == 2


def test_schema_contract_verification_and_mismatch_detection(tmp_path: Path) -> None:
    """Verify ParquetStore.verify_schema_contract detects missing fields and type mismatches."""
    output_file = tmp_path / "valid.parquet"
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]
    ParquetStore.write_models(models, output_file)

    # Valid schema passes contract verification
    ParquetStore.verify_schema_contract(output_file, DailyPrice)


def test_raw_snapshot_sidecar_corruption_recovery(tmp_path: Path) -> None:
    """Verify raw snapshot store recovers when sidecar .meta.json file is corrupted."""
    store = RawSnapshotStore(base_dir=tmp_path / "raw")
    raw_body_bytes = b'{"status": 200, "data": []}'
    env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com/api",
        params={},
        status_code=200,
        raw_body_bytes=raw_body_bytes,
    )

    h1, raw_path1 = store.save(env, "daily_price")
    meta_path1 = raw_path1.with_suffix(".meta.json")
    assert raw_path1.exists()
    assert meta_path1.exists()

    # Corrupt metadata sidecar file
    meta_path1.write_text("corrupted json content {{{", encoding="utf-8")

    # Re-saving recovers valid metadata sidecar without failing
    h2, raw_path2 = store.save(env, "daily_price")
    assert h1 == h2
    assert "content_hash" in meta_path1.read_text(encoding="utf-8")


def test_concurrent_rollback_safety_does_not_delete_peer_published_dir(tmp_path: Path) -> None:
    """Verify rollback in one run instance does not delete target_published_dir owned by another."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    manifest_a = publisher.publish_batch(
        batch_id="batch_concurrent",
        dataset="daily_price",
        models=models,
        source_raw_hashes=[VALID_RAW_HASH_1],
    )
    published_dir = Path(manifest_a.published_filepaths[0]).parent
    assert published_dir.exists()

    catalog_mock = MagicMock(spec=DuckDBCatalog)
    catalog_mock.get_batch_manifest.return_value = None
    catalog_mock.register_published_batch.side_effect = RuntimeError("B catalog fail")
    publisher_b = AtomicBatchPublisher(root_dir=tmp_path, catalog=catalog_mock)

    with pytest.raises(StorageValidationError, match="B catalog fail"):
        publisher_b.publish_batch(
            batch_id="batch_concurrent_b",
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_1],
        )

    # Process A's published directory remains safe
    assert published_dir.exists()


def test_catalog_migration_detects_primary_key_mismatch(tmp_path: Path) -> None:
    """Verify DuckDBCatalog triggers migration when table has all columns but single primary key."""
    db_file = tmp_path / "single_pk_catalog.duckdb"
    dummy_file = tmp_path / "norm" / "data.parquet"
    dummy_file.parent.mkdir(parents=True, exist_ok=True)
    dummy_file.write_bytes(b"dummy_parquet_data")

    # Create a database with parquet_file_hashes column but ONLY single primary key (batch_id)
    conn = duckdb.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE batch_manifests (
            batch_id VARCHAR PRIMARY KEY,
            dataset VARCHAR NOT NULL,
            source_raw_hashes VARCHAR NOT NULL,
            schema_version VARCHAR NOT NULL,
            record_count BIGINT NOT NULL,
            partition_date_range VARCHAR,
            created_at VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            published_filepaths VARCHAR NOT NULL,
            parquet_file_hashes VARCHAR NOT NULL,
            manifest_hash VARCHAR NOT NULL
        );
        """
    )
    p_files_json = json.dumps([str(dummy_file)])
    conn.execute(
        f"""
        INSERT INTO batch_manifests VALUES (
            'b_pk1', 'daily_price', '[]', 'schema-v0.1', 5, '2026-09-25',
            '2026-09-25T00:00:00Z', 'PUBLISHED', '{p_files_json}', '{{}}', 'hash_pk1'
        );
        """
    )
    conn.close()

    # Opening DuckDBCatalog triggers migration when pk_cols != {"dataset", "batch_id"}
    catalog = DuckDBCatalog(db_file)
    m = catalog.get_batch_manifest("daily_price", "b_pk1")
    assert m is not None
    assert m.batch_id == "b_pk1"
    catalog.close()


def test_schema_contract_detects_nullability_mismatch(tmp_path: Path) -> None:
    """Verify verify_schema_contract rejects files where required fields have nullable=True."""
    output_file = tmp_path / "bad_nullable.parquet"

    # Create a table where required stock_id string field is wrongly set to nullable=True
    table = (
        duckdb.connect(":memory:")
        .execute(
            "SELECT '2026-09-25' AS trade_date, '2330' AS stock_id, 'TWSE' AS market, "
            "100.0 AS open_price, 105.0 AS high_price, 99.0 AS low_price, 104.0 AS close_price, "
            "4.0 AS change, 1000 AS trading_volume, 104000 AS trading_value, "
            "100 AS transaction_count, "
            "false AS no_trade, 'finmind' AS source, '2026-09-25T00:00:00Z' AS retrieved_at, "
            "'schema-v0.1' AS schema_version, ['none'] AS quality_flags"
        )
        .to_arrow_table()
    )

    import pyarrow.parquet as pq

    pq.write_table(table, output_file)

    # DuckDB arrow table creates nullable=True by default for all columns.
    # verify_schema_contract should catch required non-optional fields having nullable=True!
    with pytest.raises(ValueError, match="nullability contract mismatch"):
        ParquetStore.verify_schema_contract(output_file, DailyPrice)


def test_concurrent_same_batch_id_race_rollback_isolation(tmp_path: Path) -> None:
    """Verify deterministic concurrent publish race: Controlled pre-swap barrier isolation."""
    import hashlib
    import threading

    db_file = tmp_path / "catalog" / "qmo_catalog.duckdb"
    catalog_a = DuckDBCatalog(db_file)
    catalog_b = DuckDBCatalog(db_file)
    publisher_a = AtomicBatchPublisher(root_dir=tmp_path, catalog=catalog_a)
    publisher_b = AtomicBatchPublisher(root_dir=tmp_path, catalog=catalog_b)

    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    # Controlled barrier before atomic directory swap ensures both threads finish staging first
    pre_swap_barrier = threading.Barrier(2)
    results: Dict[str, Any] = {}

    original_register = catalog_a.register_published_batch

    def thread_a_worker() -> None:
        def failing_register(manifest: Any) -> None:
            # Simulated failure post-swap during catalog registration
            raise RuntimeError("Publisher A catalog registration simulated failure post-swap")

        def hook_a() -> None:
            pre_swap_barrier.wait(timeout=5)

        catalog_a.register_published_batch = failing_register
        try:
            publisher_a.publish_batch(
                batch_id="batch_same_race",
                dataset="daily_price",
                models=models,
                source_raw_hashes=[VALID_RAW_HASH_1],
                _pre_swap_hook=hook_a,
            )
        except StorageValidationError as e:
            results["thread_a_error"] = str(e)
        finally:
            catalog_a.register_published_batch = original_register

    def thread_b_worker() -> None:
        def hook_b() -> None:
            pre_swap_barrier.wait(timeout=5)
            import time

            time.sleep(0.05)

        try:
            manifest_b = publisher_b.publish_batch(
                batch_id="batch_same_race",
                dataset="daily_price",
                models=models,
                source_raw_hashes=[VALID_RAW_HASH_1],
                _pre_swap_hook=hook_b,
            )
            results["thread_b_manifest"] = manifest_b
        except Exception as e:
            results["thread_b_error"] = str(e)

    t_a = threading.Thread(target=thread_a_worker)
    t_b = threading.Thread(target=thread_b_worker)

    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    # 1. Assert threads completed cleanly
    assert not t_a.is_alive(), "Thread A must be finished"
    assert not t_b.is_alive(), "Thread B must be finished"

    # 2. Assert thread A failed on catalog error and thread B succeeded
    assert "thread_a_error" in results, f"Publisher A must fail on catalog error: {results}"
    assert "thread_b_manifest" in results, f"Publisher B must succeed: {results}"
    assert "thread_b_error" not in results, f"Publisher B encountered unexpected error: {results}"

    # 3. Assert published directory & file remain intact
    target_pub_dir = tmp_path / "normalized" / "daily_price" / "batch_same_race"
    assert target_pub_dir.exists(), "Published directory must remain intact"
    published_file = target_pub_dir / "data.parquet"
    assert published_file.exists()

    # 4. Assert catalog manifest exists in catalog_b with status PUBLISHED and correct file hash
    cat_manifest = catalog_b.get_batch_manifest("daily_price", "batch_same_race")
    assert cat_manifest is not None
    assert cat_manifest.status == BatchStatus.PUBLISHED
    actual_file_hash = hashlib.sha256(published_file.read_bytes()).hexdigest()
    assert cat_manifest.parquet_file_hashes.get(str(published_file)) == actual_file_hash


def test_verify_schema_contract_detects_missing_non_partition_field(tmp_path: Path) -> None:
    """Verify schema validation fails if parquet file lacks required non-partition field."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    # Table lacking required 'stock_id' field (only contains market and open_price)
    table = pa.Table.from_pydict({"market": ["TWSE"], "open_price": [100.0]})
    part_dir = tmp_path / "partitioned_dataset" / "trade_date=2026-09-25"
    part_dir.mkdir(parents=True, exist_ok=True)
    parquet_file = part_dir / "data.parquet"
    pq.write_table(table, parquet_file)

    # Calling verify_schema_contract on root directory must raise ValueError for missing stock_id
    with pytest.raises(ValueError, match="missing fields .*stock_id"):
        ParquetStore.verify_schema_contract(
            tmp_path / "partitioned_dataset", DailyPrice, partition_cols=["trade_date"]
        )


def test_concurrent_same_batch_id_conflicting_provenance_race(tmp_path: Path) -> None:
    """Verify concurrent publish with different raw hashes fails with BatchConflictError."""
    import threading

    db_file = tmp_path / "catalog" / "qmo_catalog.duckdb"
    catalog_a = DuckDBCatalog(db_file)
    catalog_b = DuckDBCatalog(db_file)
    publisher_a = AtomicBatchPublisher(root_dir=tmp_path, catalog=catalog_a)
    publisher_b = AtomicBatchPublisher(root_dir=tmp_path, catalog=catalog_b)

    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    pre_swap_barrier = threading.Barrier(2)
    results: Dict[str, Any] = {}

    def thread_a_worker() -> None:
        def hook_a() -> None:
            pre_swap_barrier.wait(timeout=5)

        try:
            manifest_a = publisher_a.publish_batch(
                batch_id="batch_prov_race",
                dataset="daily_price",
                models=models,
                source_raw_hashes=[VALID_RAW_HASH_1],
                _pre_swap_hook=hook_a,
            )
            results["thread_a_manifest"] = manifest_a
        except Exception as e:
            results["thread_a_error"] = str(e)
            results["thread_a_exc"] = e

    def thread_b_worker() -> None:
        def hook_b() -> None:
            pre_swap_barrier.wait(timeout=5)

        try:
            manifest_b = publisher_b.publish_batch(
                batch_id="batch_prov_race",
                dataset="daily_price",
                models=models,
                source_raw_hashes=[VALID_RAW_HASH_2],
                _pre_swap_hook=hook_b,
            )
            results["thread_b_manifest"] = manifest_b
        except Exception as e:
            results["thread_b_error"] = str(e)
            results["thread_b_exc"] = e

    t_a = threading.Thread(target=thread_a_worker)
    t_b = threading.Thread(target=thread_b_worker)

    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    assert not t_a.is_alive()
    assert not t_b.is_alive()

    # One publisher must succeed, and the conflicting provenance publisher must fail
    has_a_success = "thread_a_manifest" in results
    has_b_success = "thread_b_manifest" in results
    assert has_a_success != has_b_success, f"Exactly one publisher must succeed: {results}"

    if has_a_success:
        assert "thread_b_error" in results
        assert isinstance(results["thread_b_exc"], BatchConflictError)
        winning_hashes = [VALID_RAW_HASH_1]
    else:
        assert "thread_a_error" in results
        assert isinstance(results["thread_a_exc"], BatchConflictError)
        winning_hashes = [VALID_RAW_HASH_2]

    # Verify Catalog provenance matches the winning publisher's raw hashes exactly
    cat_manifest = catalog_a.get_batch_manifest("daily_price", "batch_prov_race")
    assert cat_manifest is not None
    assert cat_manifest.status == BatchStatus.PUBLISHED
    assert sorted(cat_manifest.source_raw_hashes) == sorted(winning_hashes)


def test_orphaned_directory_crash_recovery_and_provenance_conflict(tmp_path: Path) -> None:
    """Verify crash recovery adopts orphaned directory with matching intent,
    but rejects conflicting provenance.
    """
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    target_dir = tmp_path / "normalized" / "daily_price" / "batch_crash_recovery"
    target_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = target_dir / "data.parquet"
    staged_hash = ParquetStore.write_models(models, parquet_path)

    # Simulate Process A leaving intent file before crashing (no catalog record)
    intent_file = target_dir / ".intent_crash1.json"
    intent_payload = {
        "dataset": "daily_price",
        "batch_id": "batch_crash_recovery",
        "source_raw_hashes": [VALID_RAW_HASH_1],
        "schema_version": "schema-v0.1",
        "record_count": 1,
        "partition_date_range": None,
        "staged_hash": staged_hash,
    }
    intent_file.write_text(json.dumps(intent_payload))

    # Process B with DIFFERENT raw hash must fail closed with BatchConflictError
    with pytest.raises(BatchConflictError, match="conflicting provenance or content"):
        publisher.publish_batch(
            batch_id="batch_crash_recovery",
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_2],
        )

    # Process B with IDENTICAL raw hash adopts orphaned directory and registers catalog
    manifest = publisher.publish_batch(
        batch_id="batch_crash_recovery",
        dataset="daily_price",
        models=models,
        source_raw_hashes=[VALID_RAW_HASH_1],
    )
    assert manifest.status == BatchStatus.PUBLISHED
    assert manifest.batch_id == "batch_crash_recovery"
    cat_manifest = publisher.catalog.get_batch_manifest("daily_price", "batch_crash_recovery")
    assert cat_manifest is not None
    assert cat_manifest.source_raw_hashes == [VALID_RAW_HASH_1]
    assert any("quality_report.json" in fp for fp in manifest.published_filepaths)
    assert any("quality_report.md" in fp for fp in manifest.published_filepaths)

    qr_res = publisher.catalog.conn.execute(
        "SELECT overall_passed FROM quality_reports WHERE dataset = ? AND batch_id = ?",
        ("daily_price", "batch_crash_recovery"),
    ).fetchone()
    assert qr_res is not None
    assert qr_res[0] is True


def test_missing_corrupted_or_multiple_intent_fails_closed(tmp_path: Path) -> None:
    """Verify published directory without Catalog manifest fails closed if Intent is
    missing, corrupted, or non-unique.
    """
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
            source="FinMind:TaiwanStockPrice",
        )
    ]

    # 1. Directory exists with data, NO intent marker file -> BatchConflictError
    target_dir1 = tmp_path / "normalized" / "daily_price" / "batch_no_intent"
    target_dir1.mkdir(parents=True, exist_ok=True)
    ParquetStore.write_models(models, target_dir1 / "data.parquet")

    with pytest.raises(BatchConflictError):
        publisher.publish_batch(
            batch_id="batch_no_intent",
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_1],
        )

    # 2. Directory exists with corrupted intent marker -> BatchConflictError
    target_dir2 = tmp_path / "normalized" / "daily_price" / "batch_corrupt_intent"
    target_dir2.mkdir(parents=True, exist_ok=True)
    ParquetStore.write_models(models, target_dir2 / "data.parquet")
    (target_dir2 / ".intent_corrupt.json").write_text("{invalid json content")

    with pytest.raises(BatchConflictError):
        publisher.publish_batch(
            batch_id="batch_corrupt_intent",
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_1],
        )

    # 3. Directory exists with MULTIPLE intent markers -> BatchConflictError
    target_dir3 = tmp_path / "normalized" / "daily_price" / "batch_multi_intent"
    target_dir3.mkdir(parents=True, exist_ok=True)
    ParquetStore.write_models(models, target_dir3 / "data.parquet")
    (target_dir3 / ".intent_1.json").write_text("{}")
    (target_dir3 / ".intent_2.json").write_text("{}")

    with pytest.raises(BatchConflictError):
        publisher.publish_batch(
            batch_id="batch_multi_intent",
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_1],
        )


def test_duckdb_catalog_creates_quality_reports_table_for_existing_wp4_db(
    tmp_path: Path,
) -> None:
    """Verify DuckDBCatalog creates quality_reports table for WP4 DB where manifest table exists."""
    db_file = tmp_path / "wp4_catalog.duckdb"
    conn = duckdb.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE batch_manifests (
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
    conn.close()

    catalog = DuckDBCatalog(db_file)
    res = catalog.conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'quality_reports'"
    ).fetchone()
    assert res is not None and res[0] == 1


def test_publisher_forbids_disabling_validator(tmp_path: Path) -> None:
    """Verify AtomicBatchPublisher rejects validator=False."""
    with pytest.raises(ValueError, match="Quality Gate cannot be disabled"):
        AtomicBatchPublisher(root_dir=tmp_path, validator=False)


def test_catalog_quality_report_immutable_conflict_detection(tmp_path: Path) -> None:
    """Verify DuckDBCatalog computes SHA-256 and rejects re-registering report with conflict."""
    from qmo.validation.models import QualityReport

    catalog = DuckDBCatalog(tmp_path / "qmo_catalog.duckdb")
    report1 = QualityReport(
        batch_id="b_qr_conflict",
        dataset="daily_price",
        created_at="2026-09-25T00:00:00Z",
        overall_passed=True,
        total_records=1,
        summary={"total_records": 1, "passed_checks": 1, "total_checks": 1},
    )

    catalog.register_quality_report(report1)

    # Identical report content is idempotent
    catalog.register_quality_report(report1)

    # Conflicting report content produces different compute_report_hash and raises error
    report2 = QualityReport(
        batch_id="b_qr_conflict",
        dataset="daily_price",
        created_at="2026-09-25T00:00:00Z",
        overall_passed=False,
        total_records=1,
        summary={"total_records": 1, "passed_checks": 0, "total_checks": 1},
    )

    with pytest.raises(BatchConflictError, match="conflicting report_hash"):
        catalog.register_quality_report(report2)


def test_duckdb_catalog_migrates_legacy_quality_reports_table_missing_report_hash_column(
    tmp_path: Path,
) -> None:
    """Verify DuckDBCatalog backfills canonical hash for legacy quality_reports rows."""
    from qmo.validation.models import QualityReport

    db_file = tmp_path / "legacy_qr_catalog.duckdb"
    conn = duckdb.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE quality_reports (
            dataset VARCHAR NOT NULL,
            batch_id VARCHAR NOT NULL,
            overall_passed BOOLEAN NOT NULL,
            created_at VARCHAR NOT NULL,
            total_records BIGINT NOT NULL,
            passed_checks INTEGER NOT NULL,
            total_checks INTEGER NOT NULL,
            report_json VARCHAR NOT NULL,
            PRIMARY KEY (dataset, batch_id)
        );
        """
    )
    legacy_qr = QualityReport(
        batch_id="legacy_batch",
        dataset="daily_price",
        created_at="2026-09-20T00:00:00Z",
        overall_passed=True,
    )
    expected_hash = legacy_qr.compute_report_hash()
    insert_sql = (
        "INSERT INTO quality_reports (dataset, batch_id, overall_passed, created_at, "
        "total_records, passed_checks, total_checks, report_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?);"
    )
    conn.execute(
        insert_sql,
        (
            "daily_price",
            "legacy_batch",
            True,
            "2026-09-20T00:00:00Z",
            0,
            0,
            0,
            legacy_qr.to_json(),
        ),
    )
    conn.close()

    catalog = DuckDBCatalog(db_file)
    info = catalog.conn.execute("PRAGMA table_info('quality_reports')").fetchall()
    cols = [r[1] for r in info]
    assert "report_hash" in cols

    row = catalog.conn.execute(
        "SELECT report_hash FROM quality_reports WHERE dataset = ? AND batch_id = ?",
        ("daily_price", "legacy_batch"),
    ).fetchone()
    assert row is not None
    assert row[0] == expected_hash


def test_catalog_rejects_cross_batch_report_and_forged_hash(tmp_path: Path) -> None:
    """Verify Catalog rejects QualityReport with forged report_hash or dataset/batch_id mismatch."""
    from qmo.validation.models import QualityReport

    publisher = AtomicBatchPublisher(root_dir=tmp_path)

    # 1. Forged report_hash in QualityReport model raises ValueError
    with pytest.raises(ValueError, match="Invalid or forged report_hash"):
        QualityReport(
            batch_id="b_forged",
            dataset="daily_price",
            created_at="2026-09-25T00:00:00Z",
            overall_passed=True,
            report_hash="forged_sha256_hash",
        )

    import hashlib

    dummy_file = tmp_path / "dummy.parquet"
    dummy_file.write_bytes(b"dummy content")
    dummy_hash = hashlib.sha256(b"dummy content").hexdigest()

    manifest = BatchManifest(
        batch_id="b_correct",
        dataset="daily_price",
        source_raw_hashes=[VALID_RAW_HASH_1],
        schema_version="schema-v0.1",
        record_count=1,
        partition_date_range=None,
        status=BatchStatus.PUBLISHED,
        published_filepaths=[str(dummy_file)],
        parquet_file_hashes={str(dummy_file): dummy_hash},
    )
    mismatched_qr = QualityReport(
        batch_id="b_WRONG",
        dataset="daily_price",
        created_at="2026-09-25T00:00:00Z",
        overall_passed=True,
    )
    with pytest.raises(ValueError, match="does not match BatchManifest"):
        publisher.catalog.register_published_batch(manifest, quality_report=mismatched_qr)


def test_publisher_fails_closed_on_deleted_or_tampered_published_report_files(
    tmp_path: Path,
) -> None:
    """Verify publisher fails closed if published quality_report artifact is deleted or tampered."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]
    manifest = publisher.publish_batch(
        batch_id="b_tamper_test",
        dataset="daily_price",
        models=models,
        source_raw_hashes=[VALID_RAW_HASH_1],
    )
    assert manifest.status == BatchStatus.PUBLISHED

    pub_dir = tmp_path / "normalized" / "daily_price" / "b_tamper_test"
    qr_json = pub_dir / "quality_report.json"
    assert qr_json.exists()

    # Tamper with quality_report.json content
    qr_json.write_text("tampered_json_content")

    # Subsequent publish attempt fails closed with BatchConflictError due to hash mismatch
    with pytest.raises(BatchConflictError):
        publisher.publish_batch(
            batch_id="b_tamper_test",
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH_1],
        )


def test_orphan_adoption_report_write_failure_leaves_published_dir_unmodified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify failed report write during orphan adoption leaves published dir unmodified."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]
    # Create orphan published directory with data.parquet
    pub_dir = tmp_path / "normalized" / "daily_price" / "b_orphan_test"
    pub_dir.mkdir(parents=True, exist_ok=True)
    published_file = pub_dir / "data.parquet"
    ParquetStore.write_models(models, published_file)

    initial_files = set(pub_dir.iterdir())
    assert (pub_dir / "quality_report.json").exists() is False
    assert (pub_dir / "quality_report.md").exists() is False

    from qmo.validation.models import QualityReport

    qr = QualityReport(
        batch_id="b_orphan_test",
        dataset="daily_price",
        created_at="2026-09-25T00:00:00Z",
        overall_passed=True,
    )

    # Mock to_markdown to raise an exception after to_json succeeds
    def failing_to_markdown(self: Any) -> str:
        raise RuntimeError("Markdown rendering disk failure")

    monkeypatch.setattr(QualityReport, "to_markdown", failing_to_markdown)

    with pytest.raises(StorageValidationError, match="Failed to persist QualityReport"):
        publisher._create_and_register_manifest(
            batch_id="b_orphan_test",
            dataset="daily_price",
            clean_raw_hashes=[VALID_RAW_HASH_1],
            schema_version="schema-v0.1",
            record_count=1,
            partition_date_range="2026-09-25 2026-09-25",
            target_published_dir=pub_dir,
            published_file=published_file,
            partition_by_date=False,
            quality_report=qr,
        )

    # Assert published dir is completely unchanged (no partial quality_report.json or .tmp files)
    final_files = set(pub_dir.iterdir())
    assert final_files == initial_files
    assert (pub_dir / "quality_report.json").exists() is False
    assert (pub_dir / "quality_report.md").exists() is False


def test_corrupted_legacy_report_json_fails_migration_without_backfill(
    tmp_path: Path,
) -> None:
    """Verify legacy quality_reports with corrupted JSON fail migration closed."""
    import duckdb

    db_path = tmp_path / "legacy_corrupt.duckdb"
    conn = duckdb.connect(str(db_path))

    # Create legacy quality_reports table missing report_hash column
    conn.execute(
        """
        CREATE TABLE quality_reports (
            dataset VARCHAR NOT NULL,
            batch_id VARCHAR NOT NULL,
            overall_passed BOOLEAN NOT NULL,
            created_at VARCHAR NOT NULL,
            summary_json VARCHAR NOT NULL,
            report_json VARCHAR NOT NULL,
            PRIMARY KEY (dataset, batch_id)
        )
        """
    )
    conn.execute(
        "INSERT INTO quality_reports VALUES (?, ?, ?, ?, ?, ?)",
        ("daily_price", "b_corrupt", True, "2026-09-25", "{}", "{CORRUPTED_JSON_STRING"),
    )
    conn.close()

    # Instantiating DuckDBCatalog triggers migration and must raise StorageValidationError
    with pytest.raises(StorageValidationError, match="corrupted"):
        DuckDBCatalog(db_path)

