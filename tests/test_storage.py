"""Storage Engine, Parquet, DuckDB Catalog, and Atomic Swap Tests."""

from pathlib import Path

import pytest

from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.catalog import DuckDBCatalog
from qmo.storage.manifest import BatchManifest, BatchStatus
from qmo.storage.parquet_store import ParquetStore
from qmo.storage.publisher import AtomicBatchPublisher, StorageValidationError
from qmo.storage.raw_store import RawSnapshotStore


def test_raw_snapshot_store_immutability(tmp_path: Path) -> None:
    """Verify raw snapshot store uses content hash and skips re-writing duplicates."""
    store = RawSnapshotStore(base_dir=tmp_path / "raw")

    env = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"dataset": "TaiwanStockPrice", "data_id": "2330"},
        status_code=200,
        raw_body_bytes=b'{"status": 200, "msg": "success", "data": []}',
    )

    hash1, path1 = store.save(env, "TaiwanStockPrice")
    assert path1.exists()
    assert hash1 in path1.name
    mtime1 = path1.stat().st_mtime_ns

    # Re-saving identical payload content hash skips re-writing
    hash2, path2 = store.save(env, "TaiwanStockPrice")
    assert hash1 == hash2
    assert path1 == path2
    mtime2 = path2.stat().st_mtime_ns
    assert mtime1 == mtime2


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
        source_raw_hashes=["hash123"],
    )

    assert manifest.status == BatchStatus.PUBLISHED
    assert manifest.record_count == 1
    assert len(manifest.published_filepaths) == 1

    published_file = Path(manifest.published_filepaths[0])
    assert published_file.exists()
    assert "normalized/daily_price/batch_20260925_001.parquet" in str(published_file)

    # Verify staging directory is cleaned up
    staging_file = tmp_path / "staging" / batch_id / "daily_price.parquet"
    assert not staging_file.exists()

    # Verify DuckDB catalog registered published batch
    cat_manifest = publisher.catalog.get_batch_manifest(batch_id)
    assert cat_manifest is not None
    assert cat_manifest.batch_id == batch_id
    assert cat_manifest.status == BatchStatus.PUBLISHED
    assert cat_manifest.record_count == 1


def test_atomic_publisher_rollback_on_failure(tmp_path: Path) -> None:
    """Verify rollback cleans up staging and leaves existing published files untouched on error."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)

    # 1. Publish initial valid batch
    batch1_models = [
        DailyPrice(
            trade_date="2026-09-24",
            stock_id="2330",
            market="TWSE",
            open_price=90.0,
            close_price=95.0,
            trading_volume=500,
            trading_value=47500,
            source="FinMind:TaiwanStockPrice",
        )
    ]
    m1 = publisher.publish_batch(
        batch_id="batch_001",
        dataset="daily_price",
        models=batch1_models,
        source_raw_hashes=["hash111"],
    )
    published_file1 = Path(m1.published_filepaths[0])
    assert published_file1.exists()

    # 2. Attempt empty model publish (should fail during staging)
    with pytest.raises(StorageValidationError, match="Cannot publish empty batch"):
        publisher.publish_batch(
            batch_id="batch_002",
            dataset="daily_price",
            models=[],
            source_raw_hashes=["hash222"],
        )

    # Verify previous published batch remains intact
    assert published_file1.exists()
    assert publisher.catalog.get_batch_manifest("batch_001") is not None
    assert publisher.catalog.get_batch_manifest("batch_002") is None


def test_catalog_rejects_non_published_manifest(tmp_path: Path) -> None:
    """Verify DuckDB catalog rejects non-PUBLISHED manifests or missing files."""
    catalog = DuckDBCatalog(tmp_path / "catalog.duckdb")

    m_staged = BatchManifest(
        batch_id="b_staged",
        dataset="daily_price",
        status=BatchStatus.STAGED,
    )
    with pytest.raises(ValueError, match="Cannot register batch with non-PUBLISHED status"):
        catalog.register_published_batch(m_staged)

    m_pub_missing = BatchManifest(
        batch_id="b_missing",
        dataset="daily_price",
        status=BatchStatus.PUBLISHED,
        published_filepaths=[str(tmp_path / "non_existent.parquet")],
    )
    with pytest.raises(FileNotFoundError, match="Published file does not exist"):
        catalog.register_published_batch(m_pub_missing)


def test_idempotent_duplicate_batch_publish(tmp_path: Path) -> None:
    """Verify re-publishing the same batch ID is idempotent and clean."""
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

    m1 = publisher.publish_batch(
        batch_id="batch_idemp",
        dataset="daily_price",
        models=models,
        source_raw_hashes=["hash1"],
    )

    m2 = publisher.publish_batch(
        batch_id="batch_idemp",
        dataset="daily_price",
        models=models,
        source_raw_hashes=["hash1"],
    )

    assert m1.batch_id == m2.batch_id
    assert m2.status == BatchStatus.PUBLISHED
    cat_manifest = publisher.catalog.get_batch_manifest("batch_idemp")
    assert cat_manifest is not None
    assert cat_manifest.manifest_hash == m2.manifest_hash
