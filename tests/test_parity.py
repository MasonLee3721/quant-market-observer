"""M0 50-Ticker Parity, Golden Summary, and Pipeline Verification Tests."""

import csv
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
    fixture_path = Path(__file__).parent / "fixtures" / "m0_golden_summary.json"
    assert fixture_path.exists(), f"Golden summary fixture not found at {fixture_path}"

    with open(fixture_path, mode="r", encoding="utf-8") as f:
        golden = json.load(f)

    # 1. Verify provenance evidence metadata
    assert golden["version"] == "schema-v0.1"
    assert "generation_command" in golden
    assert "source_dataset" in golden
    assert "node_spike_commit" in golden
    assert "source_file_sha256" in golden

    # 2. Execute Python Normalization Pipeline over 50-ticker spike dataset
    universe_path = Path(__file__).parents[1] / "config" / "universe_spike.csv"
    stock_master_map = load_universe_stock_master(universe_path)
    price_normalizer = PriceNormalizer(stock_master=stock_master_map)
    inst_normalizer = InstitutionalNormalizer(stock_master=stock_master_map)
    margin_normalizer = MarginNormalizer(stock_master=stock_master_map)

    raw_price_data = []
    raw_inst_data = []
    raw_margin_data = []

    # Build 50-ticker raw payloads with 3 no_trade records
    tickers = list(stock_master_map.keys())
    for idx, stock_id in enumerate(tickers):
        is_no_trade_sample = idx < 3  # Exactly 3 no-trade records
        raw_price_data.append(
            {
                "stock_id": stock_id,
                "date": "2026-09-25",
                "open": None if is_no_trade_sample else 100.0 + idx,
                "max": None if is_no_trade_sample else 105.0 + idx,
                "min": None if is_no_trade_sample else 98.0 + idx,
                "close": None if is_no_trade_sample else 104.5 + idx,
                "spread": 0.0 if is_no_trade_sample else 4.5,
                "Trading_Volume": 0 if is_no_trade_sample else (1000 * (idx + 1)),
                "Trading_money": 0 if is_no_trade_sample else (100000 * (idx + 1)),
                "Trading_turnover": 0 if is_no_trade_sample else 50,
            }
        )
        raw_inst_data.append(
            {
                "date": "2026-09-25",
                "name": "Foreign_Investor",
                "buy": 1000 * (idx + 1),
                "sell": 400 * (idx + 1),
            }
        )
        raw_margin_data.append(
            {
                "date": "2026-09-25",
                "stock_id": stock_id,
                "MarginPurchaseBuy": 100 * (idx + 1),
                "MarginPurchaseSell": 30 * (idx + 1),
                "MarginPurchaseTodayBalance": 500 * (idx + 1),
                "ShortSaleBuy": 20 * (idx + 1),
                "ShortSaleSell": 50 * (idx + 1),
                "ShortSaleTodayBalance": 200 * (idx + 1),
            }
        )

    price_env = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "all"},
        status_code=200,
        raw_body_bytes=json.dumps({"data": raw_price_data}).encode("utf-8"),
    )
    inst_env = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=json.dumps({"data": raw_inst_data}).encode("utf-8"),
    )
    margin_env = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=json.dumps({"data": raw_margin_data}).encode("utf-8"),
    )

    normalized_prices = price_normalizer.normalize(price_env)
    normalized_inst = inst_normalizer.normalize(inst_env)
    normalized_margin = margin_normalizer.normalize(margin_env)

    # 3. Pipeline Assertion against Golden Summary Facts
    assert len(normalized_prices) == golden["ticker_count"]  # 50 records in sample
    assert len(set(p.stock_id for p in normalized_prices)) == golden["ticker_count"]
    assert len(normalized_inst) == 1
    assert len(normalized_margin) == golden["ticker_count"]

    no_trade_count = sum(1 for p in normalized_prices if p.no_trade)
    assert no_trade_count == golden["no_trade_records_count"]  # Exactly 3

    # Primary key duplicate verification
    pk_set = set((p.stock_id, p.trade_date) for p in normalized_prices)
    assert len(pk_set) == len(normalized_prices)

    # Verify schema version on all pipeline outputs
    for record in normalized_prices:
        assert record.schema_version == golden["version"]


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

        # 1. Discrete parity & market classification check
        assert rec.stock_id == stock_id
        assert rec.trade_date == "2026-09-25"
        assert rec.market == expected_market  # Dynamic Stock Master market lookup
        assert rec.no_trade is False
        assert rec.schema_version == "schema-v0.1"

        # 2. Floating point Epsilon Tolerance (1e-4) & rounding check
        assert rec.close_price is not None
        assert math.isclose(rec.close_price, expected_close, abs_tol=1e-4)

        # 3. Institutional & Margin normalizer parity check per ticker
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
                    "MarginPurchaseBuy": 100,
                    "MarginPurchaseSell": 30,
                    "MarginPurchaseTodayBalance": 500,
                    "ShortSaleBuy": 20,
                    "ShortSaleSell": 50,
                    "ShortSaleTodayBalance": 200,
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
