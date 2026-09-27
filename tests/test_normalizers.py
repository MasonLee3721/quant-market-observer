"""Normalizer Tests for Zero, Null, and No-Trade Semantics."""

import json

import pytest

from qmo.normalizers.price import PriceNormalizer
from qmo.providers.protocols import RawResponseEnvelope


@pytest.mark.parametrize(
    "trading_volume,open_p,close_p,expected_no_trade",
    [
        (1000, 100.0, 105.0, False),  # Normal trade
        (0, 0.0, 0.0, True),  # Halted / No trade
        (0, None, None, True),  # Missing price
        (500, None, None, True),  # Volume > 0 but null price
    ],
)
def test_price_normalizer_no_trade_semantics(
    trading_volume: int,
    open_p: float | None,
    close_p: float | None,
    expected_no_trade: bool,
) -> None:
    """Verify strict no_trade semantics and null conversion."""
    payload_dict = {
        "data": [
            {
                "stock_id": "2330",
                "date": "2026-09-27",
                "open": open_p,
                "max": open_p,
                "min": close_p,
                "close": close_p,
                "Trading_Volume": trading_volume,
                "Trading_money": trading_volume * 100 if trading_volume else 0,
            }
        ]
    }
    raw_body_str = json.dumps(payload_dict)

    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "2330"},
        status_code=200,
        raw_body=raw_body_str,
    )

    normalizer = PriceNormalizer()
    records = normalizer.normalize(envelope)

    assert len(records) == 1
    rec = records[0]
    assert rec.no_trade == expected_no_trade
    if expected_no_trade:
        assert rec.open_price is None
        assert rec.high_price is None
        assert rec.low_price is None
        assert rec.close_price is None
    else:
        assert rec.close_price == close_p
