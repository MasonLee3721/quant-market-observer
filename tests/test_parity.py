"""Parity Tests Comparing Node Spike Results and Python Normalizer."""

import math

from qmo.normalizers.price import PriceNormalizer
from qmo.providers.protocols import RawResponseEnvelope


def test_discrete_and_floating_parity_rules() -> None:
    """Verify discrete fields 100% match and floating point values respect epsilon tolerance."""
    node_spike_record = {
        "symbol": "2330",
        "date": "2026-09-27",
        "close": 980.50,
        "no_trade": False,
    }

    raw_payload = {
        "data": [
            {
                "stock_id": "2330",
                "date": "2026-09-27",
                "open": 975.00,
                "max": 985.00,
                "min": 970.00,
                "close": 980.49999,  # Small float variation from Provider
                "Trading_Volume": 25000000,
                "Trading_money": 24500000000,
            }
        ]
    }
    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "2330"},
        status_code=200,
        raw_payload=raw_payload,
    )

    normalizer = PriceNormalizer()
    python_records = normalizer.normalize(envelope)
    python_record = python_records[0]

    # Discrete fields MUST match 100%
    assert python_record.symbol == node_spike_record["symbol"]
    assert python_record.date == node_spike_record["date"]
    assert python_record.no_trade == node_spike_record["no_trade"]

    # Floating point fields must be within epsilon tolerance (1e-4)
    assert python_record.close_price is not None
    assert math.isclose(python_record.close_price, node_spike_record["close"], abs_tol=1e-4)
