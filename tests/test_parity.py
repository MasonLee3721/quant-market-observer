"""M0 50-Ticker Parity, Golden Summary, and Pipeline Verification Tests."""

import hashlib
import json
import math
from pathlib import Path

from qmo.models.stock import load_universe_stock_master
from qmo.normalizers.institutional import InstitutionalNormalizer
from qmo.normalizers.margin import MarginNormalizer
from qmo.normalizers.price import PriceNormalizer
from qmo.providers.protocols import RawResponseEnvelope


def test_m0_golden_summary_facts() -> None:
    """Verify system matches authoritative M0 Golden Summary facts from M0 spike result."""
    summary_path = Path(__file__).parent / "fixtures" / "m0_golden_summary.json"
    assert summary_path.exists(), f"Golden summary fixture not found at {summary_path}"

    with open(summary_path, mode="r", encoding="utf-8") as f:
        golden_summary = json.load(f)

    # 1. Authoritative M0 Facts Verification
    assert golden_summary["version"] == "schema-v0.1"
    assert golden_summary["date_range"] == "2024-09-27 to 2026-09-25"
    assert golden_summary["ticker_count"] == 50
    assert golden_summary["total_price_records"] == 24193
    assert golden_summary["total_institutional_records"] == 24185
    assert golden_summary["total_margin_records"] == 24107
    assert golden_summary["primary_key_duplicates"] == 0
    assert math.isclose(golden_summary["three_table_join_ratio"], 0.9958, abs_tol=1e-4)
    assert golden_summary["no_trade_records_count"] == 3
    assert "generation_command" in golden_summary
    assert "daily_price_csv_sha256" in golden_summary
    assert "institutional_flow_csv_sha256" in golden_summary
    assert "margin_csv_sha256" in golden_summary


def test_real_m0_artifact_raw_and_csv_parity() -> None:
    """Verify real M0 raw JSON payload artifact normalization and CSV parity."""
    import sys

    import pytest

    raw_dir = Path(__file__).parents[1] / "data" / "spike" / "raw" / "TaiwanStockPrice"
    if not raw_dir.exists() or not any(raw_dir.glob("*.json")):
        pytest.skip("Real M0 raw spike payload directory not present in environment")

    root_dir = Path(__file__).parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from scripts.verify_m0_artifact import verify_m0_artifact

    summary = verify_m0_artifact()
    assert summary["total_price_records"] == 24193
    assert summary["total_institutional_records"] == 24185
    assert summary["total_margin_records"] == 24107
    assert summary["primary_key_duplicates"] == 0
    assert summary["no_trade_records_count"] == 3
    assert summary["three_table_join_ratio"] == 0.9958
    assert len(summary["daily_price_csv_sha256"]) == 64
    assert len(summary["institutional_flow_csv_sha256"]) == 64
    assert len(summary["margin_csv_sha256"]) == 64


def test_synthetic_50_ticker_parity_regression() -> None:
    """Verify discrete & floating point parity rules across 50-ticker sample fixture."""
    universe_path = Path(__file__).parents[1] / "config" / "universe_spike.csv"
    records_path = Path(__file__).parent / "fixtures" / "synthetic_50_ticker_records.json"
    summary_path = Path(__file__).parent / "fixtures" / "synthetic_50_ticker_summary.json"

    assert universe_path.exists(), f"Universe CSV not found at {universe_path}"
    assert records_path.exists(), f"Sample records fixture not found at {records_path}"
    assert summary_path.exists(), f"Sample summary fixture not found at {summary_path}"

    # 1. Dynamic SHA-256 Provenance Verification on Sample Fixture
    records_bytes = records_path.read_bytes()
    computed_sha256 = hashlib.sha256(records_bytes).hexdigest()

    with open(summary_path, mode="r", encoding="utf-8") as f:
        sample_summary = json.load(f)

    assert sample_summary["source_file_sha256"] == computed_sha256

    sample_records = json.loads(records_bytes.decode("utf-8"))

    # 50 Unique Ticker Verification
    assert len(sample_records["tickers"]) == 50
    assert len(set(sample_records["tickers"])) == 50

    stock_master_map = load_universe_stock_master(universe_path)
    assert len(stock_master_map) == 50

    price_normalizer = PriceNormalizer(stock_master=stock_master_map)
    inst_normalizer = InstitutionalNormalizer(stock_master=stock_master_map)
    margin_normalizer = MarginNormalizer(stock_master=stock_master_map)

    # 2a. Price Normalization Pipeline
    price_env = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "all"},
        status_code=200,
        raw_body_bytes=json.dumps({"data": sample_records["price_data"]}).encode("utf-8"),
    )
    normalized_prices = price_normalizer.normalize(price_env)

    # 2b. Institutional Normalization Pipeline per Ticker
    normalized_inst = []
    for stock_id, inst_rows in sample_records["institutional_data"].items():
        inst_env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="",
            params={"data_id": stock_id},
            status_code=200,
            raw_body_bytes=json.dumps({"data": inst_rows}).encode("utf-8"),
        )
        normalized_inst.extend(inst_normalizer.normalize(inst_env))

    # 2c. Margin Normalization Pipeline per Ticker
    normalized_margin = []
    for stock_id, margin_rows in sample_records["margin_data"].items():
        margin_env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="",
            params={"data_id": stock_id},
            status_code=200,
            raw_body_bytes=json.dumps({"data": margin_rows}).encode("utf-8"),
        )
        normalized_margin.extend(margin_normalizer.normalize(margin_env))

    # 3. Assert Pipeline Output Metrics Match Sample Summary
    assert len(normalized_prices) == sample_summary["total_price_records"]
    assert len(normalized_inst) == sample_summary["total_institutional_records"]
    assert len(normalized_margin) == sample_summary["total_margin_records"]

    distinct_tickers = set(p.stock_id for p in normalized_prices)
    assert len(distinct_tickers) == 50

    no_trade_count = sum(1 for p in normalized_prices if p.no_trade)
    assert no_trade_count == sample_summary["no_trade_records_count"]

    pk_set = set((p.stock_id, p.trade_date) for p in normalized_prices)
    assert len(pk_set) == len(normalized_prices)

    # Dynamic Market Lookup Verification for all 50 tickers
    for p in normalized_prices:
        expected_mkt = stock_master_map[p.stock_id].market
        assert p.market == expected_mkt
        assert p.schema_version == "schema-v0.1"

        if p.no_trade:
            assert p.open_price is None
            assert p.close_price is None
            assert "no_trade" in p.quality_flags
