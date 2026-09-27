"""Normalizer Tests for Schema Validation, Zero/Null Semantics, and Quality Flags."""

import json

import pytest

from qmo.models.price import DailyPrice
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
        (0, 0, 100.0, 105.0, True),  # M0 no_trade: prices should be nullified
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
    assert rec.schema_version == "schema-v0.1"
    if expected_no_trade:
        assert "no_trade" in rec.quality_flags
        assert rec.open_price is None
        assert rec.high_price is None
        assert rec.low_price is None
        assert rec.close_price is None


def test_invalid_date_validation_fails() -> None:
    """Verify invalid dates like 2026-99-99 raise ValueError."""
    with pytest.raises(ValueError, match="trade_date must be a valid ISO date"):
        DailyPrice(
            trade_date="2026-99-99",
            stock_id="2330",
            market="TWSE",
            close_price=100.0,
        )


def test_normalizers_raise_schema_validation_error_on_unsupported_provider() -> None:
    """Verify unsupported provider name raises SchemaValidationError."""
    envelope = RawResponseEnvelope(
        provider_name="unknown_provider",
        endpoint="",
        params={},
        status_code=200,
        raw_body_bytes=b'{"data": []}',
    )
    with pytest.raises(SchemaValidationError, match="Unsupported provider"):
        PriceNormalizer().normalize(envelope)
    with pytest.raises(SchemaValidationError, match="Unsupported provider"):
        InstitutionalNormalizer().normalize(envelope)
    with pytest.raises(SchemaValidationError, match="Unsupported provider"):
        MarginNormalizer().normalize(envelope)


def test_institutional_normalizer_multi_row_accumulation() -> None:
    """Verify InstitutionalNormalizer accumulates multi-row Foreign and Dealer sub-categories."""
    payload = {
        "data": [
            {"date": "2026-09-27", "name": "Foreign_Investor", "buy": 1000, "sell": 400},
            {"date": "2026-09-27", "name": "Foreign_Dealer_Self", "buy": 200, "sell": 50},
            {"date": "2026-09-27", "name": "Investment_Trust", "buy": 500, "sell": 100},
            {"date": "2026-09-27", "name": "Dealer_Self", "buy": 300, "sell": 100},
            {"date": "2026-09-27", "name": "Dealer_Hedging", "buy": 100, "sell": 50},
        ]
    }
    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "8069"},  # TPEx ticker
        status_code=200,
        raw_body_bytes=json.dumps(payload).encode("utf-8"),
    )
    normalizer = InstitutionalNormalizer()
    records = normalizer.normalize(envelope)

    assert len(records) == 1
    rec = records[0]
    assert rec.stock_id == "8069"
    assert rec.market == "TPEx"  # Verified market lookup!
    assert rec.foreign_buy == 1200
    assert rec.foreign_sell == 450
    assert rec.foreign_net == 750
    assert rec.investment_trust_net == 400
    assert rec.dealer_buy == 400
    assert rec.dealer_sell == 150
    assert rec.dealer_net == 250
    assert rec.total_net == 750 + 400 + 250
