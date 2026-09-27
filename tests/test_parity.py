"""M0 50-Ticker Parity, Golden Summary, and Pipeline Verification Tests."""

import csv
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
    """Verify Python normalization pipeline output strictly matches M0 Golden Summary facts."""
    summary_path = Path(__file__).parent / "fixtures" / "m0_golden_summary.json"
    records_path = Path(__file__).parent / "fixtures" / "m0_golden_records.json"
    assert summary_path.exists(), f"Golden summary fixture not found at {summary_path}"
    assert records_path.exists(), f"Golden records fixture not found at {records_path}"

    # 1. Verify source file SHA-256 provenance evidence dynamically
    records_bytes = records_path.read_bytes()
    computed_sha256 = hashlib.sha256(records_bytes).hexdigest()

    with open(summary_path, mode="r", encoding="utf-8") as f:
        golden_summary = json.load(f)

    assert golden_summary["version"] == "schema-v0.1"
    assert golden_summary["date_range"] == "2024-09-27 to 2026-09-25"
    assert golden_summary["source_file_sha256"] == computed_sha256
    assert "generation_command" in golden_summary
    assert "node_spike_commit" in golden_summary

    golden_records = json.loads(records_bytes.decode("utf-8"))

    # 2. Execute Python Normalization Pipeline over M0 golden record payloads
    universe_path = Path(__file__).parents[1] / "config" / "universe_spike.csv"
    stock_master_map = load_universe_stock_master(universe_path)
    price_normalizer = PriceNormalizer(stock_master=stock_master_map)
    inst_normalizer = InstitutionalNormalizer(stock_master=stock_master_map)
    margin_normalizer = MarginNormalizer(stock_master=stock_master_map)

    # 2a. Normalize Price Envelopes
    price_env = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "all"},
        status_code=200,
        raw_body_bytes=json.dumps({"data": golden_records["price_data"]}).encode("utf-8"),
    )
    normalized_prices = price_normalizer.normalize(price_env)

    # 2b. Normalize Institutional Envelopes per ticker
    normalized_inst = []
    for stock_id, inst_rows in golden_records["institutional_data"].items():
        inst_env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="",
            params={"data_id": stock_id},
            status_code=200,
            raw_body_bytes=json.dumps({"data": inst_rows}).encode("utf-8"),
        )
        normalized_inst.extend(inst_normalizer.normalize(inst_env))

    # 2c. Normalize Margin Envelopes per ticker
    normalized_margin = []
    for stock_id, margin_rows in golden_records["margin_data"].items():
        margin_env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="",
            params={"data_id": stock_id},
            status_code=200,
            raw_body_bytes=json.dumps({"data": margin_rows}).encode("utf-8"),
        )
        normalized_margin.extend(margin_normalizer.normalize(margin_env))

    # 3. Dynamic Pipeline Summary Facts Calculation & Assertion
    distinct_tickers = set(p.stock_id for p in normalized_prices)
    assert len(distinct_tickers) <= golden_summary["ticker_count"]

    no_trade_count = sum(1 for p in normalized_prices if p.no_trade)
    assert no_trade_count == golden_summary["no_trade_records_count"]

    # Primary key duplicate check
    pk_set = set((p.stock_id, p.trade_date) for p in normalized_prices)
    assert len(pk_set) == len(normalized_prices)
    pk_duplicates = len(normalized_prices) - len(pk_set)
    assert pk_duplicates == golden_summary["primary_key_duplicates"]

    # Calculate 3-table join ratio
    price_keys = set((p.stock_id, p.trade_date) for p in normalized_prices if not p.no_trade)
    inst_keys = set((i.stock_id, i.trade_date) for i in normalized_inst)
    margin_keys = set((m.stock_id, m.trade_date) for m in normalized_margin)
    joined_keys = price_keys.intersection(inst_keys).intersection(margin_keys)

    join_ratio = len(joined_keys) / len(price_keys) if price_keys else 1.0
    assert math.isclose(join_ratio, 1.0, abs_tol=1e-2)

    # Verify schema version on all outputs
    for p in normalized_prices:
        assert p.schema_version == golden_summary["version"]
    for i in normalized_inst:
        assert i.schema_version == golden_summary["version"]
    for m in normalized_margin:
        assert m.schema_version == golden_summary["version"]


def test_m0_50_ticker_parity_regression() -> None:
    """Verify discrete & floating point parity rules across all 50 M0 spike tickers."""
    universe_path = Path(__file__).parents[1] / "config" / "universe_spike.csv"
    assert universe_path.exists(), f"Universe CSV not found at {universe_path}"

    tickers = []
    with open(universe_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tickers.append(row)

    assert len(tickers) == 50

    stock_master_map = load_universe_stock_master(universe_path)
    assert len(stock_master_map) == 50

    tpex_count = sum(1 for sm in stock_master_map.values() if sm.market == "TPEx")
    twse_count = sum(1 for sm in stock_master_map.values() if sm.market == "TWSE")
    assert tpex_count == 3
    assert twse_count == 47

    normalizer = PriceNormalizer(stock_master=stock_master_map)
    inst_normalizer = InstitutionalNormalizer(stock_master=stock_master_map)
    margin_normalizer = MarginNormalizer(stock_master=stock_master_map)

    for idx, ticker in enumerate(tickers):
        stock_id = ticker["stock_id"]
        expected_market = ticker["market"]
        expected_close = 100.5 + idx * 0.5

        raw_price_payload = {
            "data": [
                {
                    "stock_id": stock_id,
                    "date": "2026-09-25",
                    "open": 100.0 + idx * 0.5,
                    "max": 105.0 + idx * 0.5,
                    "min": 99.0 + idx * 0.5,
                    "close": expected_close,
                    "spread": 0.5,
                    "Trading_Volume": 50000 + idx * 10,
                    "Trading_money": 5200000 + idx * 1000,
                    "Trading_turnover": 120,
                }
            ]
        }
        price_env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="https://api.finmindtrade.com/api/v4/data",
            params={"data_id": stock_id},
            status_code=200,
            raw_body_bytes=json.dumps(raw_price_payload).encode("utf-8"),
        )

        records = normalizer.normalize(price_env)
        assert len(records) == 1
        rec = records[0]

        # 1. Discrete parity & dynamic market lookup check per ticker
        assert rec.stock_id == stock_id
        assert rec.trade_date == "2026-09-25"
        assert rec.market == expected_market  # Dynamic StockMaster registry lookup!
        assert rec.no_trade is False
        assert rec.schema_version == "schema-v0.1"

        # 2. Floating point Epsilon Tolerance (1e-4) & rounding check
        assert rec.close_price is not None
        assert math.isclose(rec.close_price, expected_close, abs_tol=1e-4)

        # 3. Institutional & Margin normalizer parity check per individual ticker envelope
        raw_inst_payload = {
            "data": [
                {"date": "2026-09-25", "name": "Foreign_Investor", "buy": 1000 + idx, "sell": 400}
            ]
        }
        inst_env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="",
            params={"data_id": stock_id},
            status_code=200,
            raw_body_bytes=json.dumps(raw_inst_payload).encode("utf-8"),
        )
        inst_recs = inst_normalizer.normalize(inst_env)
        assert len(inst_recs) == 1
        assert inst_recs[0].stock_id == stock_id
        assert inst_recs[0].market == expected_market

        raw_margin_payload = {
            "data": [
                {
                    "date": "2026-09-25",
                    "stock_id": stock_id,
                    "MarginPurchaseBuy": 100 + idx,
                    "MarginPurchaseSell": 30,
                    "MarginPurchaseCashRedemption": 0,
                    "MarginPurchaseTodayBalance": 500,
                    "MarginPurchaseLimit": 1000,
                    "ShortSaleBuy": 20,
                    "ShortSaleSell": 50,
                    "ShortSaleCashRedemption": 0,
                    "ShortSaleTodayBalance": 200,
                    "ShortSaleLimit": 1000,
                }
            ]
        }
        margin_env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="",
            params={"data_id": stock_id},
            status_code=200,
            raw_body_bytes=json.dumps(raw_margin_payload).encode("utf-8"),
        )
        margin_recs = margin_normalizer.normalize(margin_env)
        assert len(margin_recs) == 1
        assert margin_recs[0].stock_id == stock_id
        assert margin_recs[0].market == expected_market
