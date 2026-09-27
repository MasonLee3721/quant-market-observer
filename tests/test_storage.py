"""Storage Engine, Parquet, DuckDB Catalog, and Atomic Swap Tests."""

from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest

from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.catalog import BatchConflictError, DuckDBCatalog
from qmo.storage.manifest import BatchManifest, BatchStatus
from qmo.storage.parquet_store import ParquetStore
from qmo.storage.publisher import AtomicBatchPublisher, StorageValidationError
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
    assert len(manifest.published_filepaths) == 1
    assert len(manifest.parquet_file_hashes) == 1

    published_file = Path(manifest.published_filepaths[0])
    assert published_file.exists()
    assert "normalized/daily_price/batch_20260925_001/data.parquet" in str(published_file)

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


