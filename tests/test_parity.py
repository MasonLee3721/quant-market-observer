"""M0 50-Ticker Parity, Golden Summary, and Rounding Policy Regression Tests."""

import csv
import json
import math
from pathlib import Path

from qmo.models.stock import load_universe_stock_master
from qmo.normalizers.price import PriceNormalizer
from qmo.providers.protocols import RawResponseEnvelope


def test_m0_golden_summary_facts() -> None:
    """Verify system matches M0 Golden Summary facts from M0 spike result."""
    fixture_path = Path(__file__).parent / "fixtures" / "m0_golden_summary.json"
    assert fixture_path.exists(), f"Golden summary fixture not found at {fixture_path}"

    with open(fixture_path, mode="r", encoding="utf-8") as f:
        golden = json.load(f)

    assert golden["ticker_count"] == 50
    assert golden["total_price_records"] == 24193
    assert golden["primary_key_duplicates"] == 0
    assert math.isclose(golden["three_table_join_ratio"], 0.9958, abs_tol=1e-4)
    assert golden["no_trade_records_count"] == 3


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

    normalizer = PriceNormalizer()

    for ticker in tickers:
        stock_id = ticker["stock_id"]
        expected_market = ticker["market"]

        raw_payload = {
            "data": [
                {
                    "stock_id": stock_id,
                    "date": "2026-09-25",
                    "open": 100.0,
                    "max": 105.0,
                    "min": 99.0,
                    "close": 104.5,
                    "spread": 4.5,
                    "Trading_Volume": 50000,
                    "Trading_money": 5200000,
                    "Trading_turnover": 120,
                }
            ]
        }
        envelope = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="https://api.finmindtrade.com/api/v4/data",
            params={"data_id": stock_id},
            status_code=200,
            raw_body_bytes=json.dumps(raw_payload).encode("utf-8"),
        )

        records = normalizer.normalize(envelope)
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
        assert math.isclose(rec.close_price, 104.5, abs_tol=1e-4)
