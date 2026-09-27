"""Normalizer Tests for Schema Validation, Zero/Null Semantics, and Quality Flags."""

import json

import pytest

from qmo.normalizers.institutional import InstitutionalNormalizer
from qmo.normalizers.margin import MarginNormalizer
from qmo.normalizers.price import PriceNormalizer
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


@pytest.mark.parametrize(
    "trading_volume,trading_value,open_p,close_p,expected_no_trade",
    [
        (1000, 100000, 100.0, 105.0, False),  # Normal trade
        (0, 0, None, None, True),  # M0 no_trade: vol==0 & val==0
        (0, 0, 0.0, 0.0, True),  # M0 no_trade: vol==0 & val==0
        (500, 50000, None, None, False),  # Trade happened but price missing -> missing_price flag
    ],
)
def test_price_normalizer_m0_no_trade_contract(
    trading_volume: int,
    trading_value: int,
    open_p: float | None,
    close_p: float | None,
    expected_no_trade: bool,
) -> None:
    """Verify strict M0 contract for no_trade semantics and quality_flags."""
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
                "Trading_money": trading_value,
            }
        ]
    }
    raw_body_bytes = json.dumps(payload_dict).encode("utf-8")

    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=raw_body_bytes,
    )

    normalizer = PriceNormalizer()
    records = normalizer.normalize(envelope)

    assert len(records) == 1
    rec = records[0]
    assert rec.no_trade == expected_no_trade
    if expected_no_trade:
        assert "no_trade" in rec.quality_flags
    elif close_p is None:
        assert "missing_price" in rec.quality_flags


def test_normalizers_raise_schema_validation_error_on_invalid_data() -> None:
    """Verify normalizers raise SchemaValidationError instead of swallowing errors."""
    normalizer = PriceNormalizer()

    # 1. Empty body
    empty_env = RawResponseEnvelope(
        provider_name="finmind", endpoint="", params={}, status_code=200, raw_body_bytes=b""
    )
    with pytest.raises(SchemaValidationError):
        normalizer.normalize(empty_env)

    # 2. Corrupted JSON
    bad_json_env = RawResponseEnvelope(
        provider_name="finmind", endpoint="", params={}, status_code=200, raw_body_bytes=b"{invalid"
    )
    with pytest.raises(SchemaValidationError):
        normalizer.normalize(bad_json_env)

    # 3. Missing 'data' array
    missing_data_env = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={},
        status_code=200,
        raw_body_bytes=b'{"msg": "ok"}',
    )
    with pytest.raises(SchemaValidationError):
        normalizer.normalize(missing_data_env)


def test_institutional_normalizer_success() -> None:
    """Verify InstitutionalNormalizer parses FinMind investor buy/sell payload."""
    payload = {
        "data": [
            {"date": "2026-09-27", "name": "Foreign_Investor", "buy": 1000, "sell": 400},
            {"date": "2026-09-27", "name": "Investment_Trust", "buy": 500, "sell": 100},
        ]
    }
    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=json.dumps(payload).encode("utf-8"),
    )
    normalizer = InstitutionalNormalizer()
    records = normalizer.normalize(envelope)

    assert len(records) == 1
    rec = records[0]
    assert rec.stock_id == "2330"
    assert rec.foreign_net == 600
    assert rec.investment_trust_net == 400
    assert rec.total_net == 1000


def test_margin_normalizer_success() -> None:
    """Verify MarginNormalizer parses FinMind margin trading payload."""
    payload = {
        "data": [
            {
                "date": "2026-09-27",
                "stock_id": "2330",
                "MarginPurchaseBuy": 100,
                "MarginPurchaseSell": 30,
                "MarginPurchaseTodayBalance": 500,
                "ShortSaleBuy": 20,
                "ShortSaleSell": 50,
                "ShortSaleTodayBalance": 200,
            }
        ]
    }
    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=json.dumps(payload).encode("utf-8"),
    )
    normalizer = MarginNormalizer()
    records = normalizer.normalize(envelope)

    assert len(records) == 1
    rec = records[0]
    assert rec.stock_id == "2330"
    assert rec.margin_purchase_buy == 100
    assert rec.margin_purchase_balance == 500
    assert rec.short_sale_sell == 50
    assert rec.short_sale_balance == 200
