"""Normalizer Tests for Schema Validation, Zero/Null Semantics, and Quality Flags."""

import json

import pytest

from qmo.models.price import DailyPrice
from qmo.models.stock import StockMaster
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


def test_utc_datetime_validation_strictness() -> None:
    """Verify retrieved_at validator accepts UTC and rejects non-UTC offsets or naive datetimes."""
    # 1. Valid UTC ISO with Z
    p1 = DailyPrice(trade_date="2026-09-27", stock_id="2330", retrieved_at="2026-09-27T03:00:00Z")
    assert p1.retrieved_at == "2026-09-27T03:00:00Z"

    # 2. Valid UTC ISO with +00:00
    p2 = DailyPrice(
        trade_date="2026-09-27", stock_id="2330", retrieved_at="2026-09-27T03:00:00+00:00"
    )
    assert "+00:00" in p2.retrieved_at

    # 3. Invalid non-UTC offset (+08:00) fails
    with pytest.raises(ValueError, match="must be UTC timezone-aware"):
        DailyPrice(
            trade_date="2026-09-27", stock_id="2330", retrieved_at="2026-09-27T11:00:00+08:00"
        )

    # 4. Naive datetime without offset fails
    with pytest.raises(ValueError, match="must be UTC timezone-aware"):
        DailyPrice(trade_date="2026-09-27", stock_id="2330", retrieved_at="2026-09-27T11:00:00")


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


def test_normalizer_dependency_injection_and_unregistered_stock_error() -> None:
    """Verify custom stock_master registry injection and error on unregistered stock_id."""
    custom_normalizer = PriceNormalizer(stock_master={})
    raw_payload = {
        "data": [
            {
                "stock_id": "9999",
                "date": "2026-09-27",
                "open": 10.0,
                "close": 10.0,
                "Trading_Volume": 1000,
                "Trading_money": 10000,
            }
        ]
    }
    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "9999"},
        status_code=200,
        raw_body_bytes=json.dumps(raw_payload).encode("utf-8"),
    )
    with pytest.raises(SchemaValidationError, match="Unknown stock_id '9999'"):
        custom_normalizer.normalize(envelope)


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
        params={"data_id": "8069"},
        status_code=200,
        raw_body_bytes=json.dumps(payload).encode("utf-8"),
    )
    normalizer = InstitutionalNormalizer()
    records = normalizer.normalize(envelope)

    assert len(records) == 1
    rec = records[0]
    assert rec.stock_id == "8069"
    assert rec.market == "TPEx"  # Verified market lookup from StockMaster registry!
    assert rec.foreign_buy == 1200
    assert rec.foreign_sell == 450
    assert rec.foreign_net == 750
    assert rec.investment_trust_net == 400
    assert rec.dealer_buy == 400
    assert rec.dealer_sell == 150
    assert rec.dealer_net == 250
    assert rec.total_net == 750 + 400 + 250


def test_margin_normalizer_success() -> None:
    """Verify MarginNormalizer parses FinMind margin trading payload."""
    payload = {
        "data": [
            {
                "date": "2026-09-27",
                "stock_id": "2330",
                "MarginPurchaseBuy": 100,
                "MarginPurchaseSell": 30,
                "MarginPurchaseCashRedemption": 10,
                "MarginPurchaseTodayBalance": 500,
                "MarginPurchaseLimit": 1000,
                "ShortSaleBuy": 20,
                "ShortSaleSell": 50,
                "ShortSaleCashRedemption": 5,
                "ShortSaleTodayBalance": 200,
                "ShortSaleLimit": 1000,
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
    assert rec.market == "TWSE"
    assert rec.margin_purchase_buy == 100
    assert rec.margin_purchase_cash_redemption == 10
    assert rec.margin_purchase_balance == 500
    assert rec.margin_purchase_quota == 1000
    assert rec.short_sale_sell == 50
    assert rec.short_sale_cash_redemption == 5
    assert rec.short_sale_balance == 200
    assert rec.short_sale_quota == 1000


def test_missing_required_fields_raise_schema_validation_error() -> None:
    """Verify missing essential schema fields cause SchemaValidationError."""
    # 1. Missing Trading_Volume in PriceNormalizer
    price_payload = {
        "data": [{"stock_id": "2330", "date": "2026-09-27", "open": 10.0, "close": 10.0}]
    }
    env_price = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=json.dumps(price_payload).encode("utf-8"),
    )
    with pytest.raises(SchemaValidationError, match="missing required field 'Trading_Volume'"):
        PriceNormalizer().normalize(env_price)

    # 2. Missing buy/sell in InstitutionalNormalizer
    inst_payload = {"data": [{"date": "2026-09-27", "name": "Foreign_Investor"}]}
    env_inst = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=json.dumps(inst_payload).encode("utf-8"),
    )
    with pytest.raises(SchemaValidationError, match="missing required field 'buy' or 'sell'"):
        InstitutionalNormalizer().normalize(env_inst)

    # 3. Missing MarginPurchaseBuy in MarginNormalizer
    margin_payload = {"data": [{"date": "2026-09-27", "stock_id": "2330"}]}
    env_margin = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=json.dumps(margin_payload).encode("utf-8"),
    )
    with pytest.raises(SchemaValidationError, match="missing required field 'MarginPurchaseBuy'"):
        MarginNormalizer().normalize(env_margin)


@pytest.mark.parametrize(
    ("provider", "params", "payload", "stock_id", "market", "expected_change"),
    [
        (
            "twse",
            {"date": "20260924"},
            {
                "stat": "OK",
                "date": "20260924",
                "tables": [
                    {"fields": ["說明"], "data": [["not quotes"]]},
                    {
                        "fields": [
                            "證券代號",
                            "成交股數",
                            "成交筆數",
                            "成交金額",
                            "開盤價",
                            "最高價",
                            "最低價",
                            "收盤價",
                            "漲跌(+/-)",
                            "漲跌價差",
                        ],
                        "data": [
                            [
                                "2330",
                                "14,557,662",
                                "12,345",
                                "36,107,476,243",
                                "2480.00",
                                "2490.00",
                                "2470.00",
                                "2475.00",
                                "<p>-</p>",
                                "5.00",
                            ]
                        ],
                    },
                ],
            },
            "2330",
            "TWSE",
            -5.0,
        ),
        (
            "tpex",
            {"d": "115/09/24"},
            {
                "stat": "OK",
                "date": "115/09/24",
                "tables": [
                    {
                        "fields": [
                            "代號",
                            "成交股數",
                            "成交金額(元)",
                            "成交筆數",
                            "開盤",
                            "最高",
                            "最低",
                            "收盤",
                            "漲跌",
                        ],
                        "data": [
                            ["8069", "1,000", "200,000", "25", "200", "205", "198", "202", "+2"]
                        ],
                    }
                ],
            },
            "8069",
            "TPEx",
            2.0,
        ),
    ],
)
def test_official_market_price_normalizer(
    provider: str,
    params: dict[str, str],
    payload: dict[str, object],
    stock_id: str,
    market: str,
    expected_change: float,
) -> None:
    registry = {
        "2330": StockMaster(symbol="2330", name="台積電", market="TWSE"),
        "8069": StockMaster(symbol="8069", name="元太", market="TPEx"),
    }
    envelope = RawResponseEnvelope(
        provider_name=provider,
        endpoint="official",
        params=params,
        status_code=200,
        raw_body_bytes=json.dumps(payload, ensure_ascii=False).encode(),
    )
    records = PriceNormalizer(stock_master=registry).normalize(envelope)
    assert len(records) == 1
    record = records[0]
    assert (record.stock_id, record.market, record.trade_date) == (stock_id, market, "2026-09-24")
    assert record.change == expected_change
    assert record.trading_volume > 0
    assert record.source.startswith(market)


def test_official_market_price_normalizer_fails_closed_on_schema_drift() -> None:
    envelope = RawResponseEnvelope(
        provider_name="twse",
        endpoint="official",
        params={"date": "20260924"},
        status_code=200,
        raw_body_bytes=b'{"stat":"OK","tables":[]}',
    )
    with pytest.raises(SchemaValidationError, match="quote table not found"):
        PriceNormalizer(stock_master={}).normalize(envelope)
