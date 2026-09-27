"""Margin Trading Normalizer Implementation."""

import json
from typing import Dict, List, Optional

from qmo.models.margin import Margin
from qmo.models.stock import StockMaster, load_universe_stock_master
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


class MarginNormalizer:
    """Normalizes raw provider payload into standardized Margin models."""

    def __init__(self, stock_master: Optional[Dict[str, StockMaster]] = None) -> None:
        if stock_master is not None:
            self.stock_master = stock_master
        else:
            self.stock_master = load_universe_stock_master()

    def get_stock_market(self, stock_id: str) -> str:
        """Lookup market for stock_id from injected StockMaster registry."""
        if stock_id in self.stock_master:
            return self.stock_master[stock_id].market
        raise SchemaValidationError(
            f"Unknown stock_id '{stock_id}' not found in StockMaster registry",
            provider="normalizer",
        )

    def normalize(self, envelope: RawResponseEnvelope) -> List[Margin]:
        """Convert raw payload envelope to a list of Margin instances."""
        if envelope.provider_name in ["twse", "tpex"]:
            raise SchemaValidationError(
                f"Normalizer for provider '{envelope.provider_name}' not yet implemented",
                provider=envelope.provider_name,
            )

        if envelope.provider_name != "finmind":
            raise SchemaValidationError(
                f"Unsupported provider for MarginNormalizer: {envelope.provider_name}",
                provider=envelope.provider_name,
            )

        if not envelope.raw_body_bytes:
            raise SchemaValidationError("Empty raw response body", provider=envelope.provider_name)

        try:
            payload = json.loads(envelope.raw_body_str)
        except Exception as e:
            raise SchemaValidationError(
                f"Failed to parse JSON body: {e}", provider=envelope.provider_name
            ) from e

        if not isinstance(payload, dict):
            raise SchemaValidationError(
                "Payload must be a JSON object", provider=envelope.provider_name
            )

        data = payload.get("data")
        if data is None or not isinstance(data, list):
            raise SchemaValidationError(
                "FinMind payload missing 'data' list", provider=envelope.provider_name
            )

        results: List[Margin] = []

        try:
            for row in data:
                if not isinstance(row, dict):
                    raise SchemaValidationError(
                        "Row item is not a dictionary", provider=envelope.provider_name
                    )

                stock_id = str(row.get("stock_id", envelope.params.get("data_id", "")))
                market = self.get_stock_market(stock_id)

                mp_red_val = (
                    row.get("MarginPurchaseCashRepayment")
                    if "MarginPurchaseCashRepayment" in row
                    else row.get("MarginPurchaseCashRedemption")
                )
                ss_red_val = (
                    row.get("ShortSaleCashRepayment")
                    if "ShortSaleCashRepayment" in row
                    else row.get("ShortSaleCashRedemption")
                )

                required_checks = [
                    ("MarginPurchaseBuy", row.get("MarginPurchaseBuy")),
                    ("MarginPurchaseSell", row.get("MarginPurchaseSell")),
                    ("MarginPurchaseCashRepayment/Redemption", mp_red_val),
                    ("MarginPurchaseTodayBalance", row.get("MarginPurchaseTodayBalance")),
                    ("MarginPurchaseLimit", row.get("MarginPurchaseLimit")),
                    ("ShortSaleBuy", row.get("ShortSaleBuy")),
                    ("ShortSaleSell", row.get("ShortSaleSell")),
                    ("ShortSaleCashRepayment/Redemption", ss_red_val),
                    ("ShortSaleTodayBalance", row.get("ShortSaleTodayBalance")),
                    ("ShortSaleLimit", row.get("ShortSaleLimit")),
                ]
                for key_name, val in required_checks:
                    if val is None:
                        raise SchemaValidationError(
                            f"Margin row missing required field '{key_name}'",
                            provider=envelope.provider_name,
                        )

                assert mp_red_val is not None
                assert ss_red_val is not None

                try:
                    mp_buy = int(row["MarginPurchaseBuy"])
                    mp_sell = int(row["MarginPurchaseSell"])
                    mp_red = int(mp_red_val)
                    mp_bal = int(row["MarginPurchaseTodayBalance"])
                    mp_limit = int(row["MarginPurchaseLimit"])

                    ss_buy = int(row["ShortSaleBuy"])
                    ss_sell = int(row["ShortSaleSell"])
                    ss_red = int(ss_red_val)
                    ss_bal = int(row["ShortSaleTodayBalance"])
                    ss_limit = int(row["ShortSaleLimit"])
                except (ValueError, TypeError) as e:
                    raise SchemaValidationError(
                        f"Invalid integer value in margin field: {e}",
                        provider=envelope.provider_name,
                    ) from e

                record = Margin(
                    trade_date=str(row.get("date", "")),
                    stock_id=stock_id,
                    market=market,
                    margin_purchase_buy=mp_buy,
                    margin_purchase_sell=mp_sell,
                    margin_purchase_cash_redemption=mp_red,
                    margin_purchase_balance=mp_bal,
                    margin_purchase_quota=mp_limit,
                    short_sale_buy=ss_buy,
                    short_sale_sell=ss_sell,
                    short_sale_cash_redemption=ss_red,
                    short_sale_balance=ss_bal,
                    short_sale_quota=ss_limit,
                    source=envelope.provider_name,
                    retrieved_at=envelope.retrieved_at,
                )
                results.append(record)
        except SchemaValidationError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            raise SchemaValidationError(
                f"Schema drift or row parsing failure: {e}", provider=envelope.provider_name
            ) from e

        return results
