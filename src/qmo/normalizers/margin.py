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

                required_keys = [
                    "MarginPurchaseBuy",
                    "MarginPurchaseSell",
                    "MarginPurchaseTodayBalance",
                    "ShortSaleBuy",
                    "ShortSaleSell",
                    "ShortSaleTodayBalance",
                ]
                for key in required_keys:
                    if key not in row or row[key] is None:
                        raise SchemaValidationError(
                            f"Margin row missing required field '{key}'",
                            provider=envelope.provider_name,
                        )

                record = Margin(
                    trade_date=str(row.get("date", "")),
                    stock_id=stock_id,
                    market=market,
                    margin_purchase_buy=int(row["MarginPurchaseBuy"]),
                    margin_purchase_sell=int(row["MarginPurchaseSell"]),
                    margin_purchase_cash_redemption=int(row.get("MarginPurchaseCashRedemption", 0)),
                    margin_purchase_balance=int(row["MarginPurchaseTodayBalance"]),
                    margin_purchase_quota=int(row.get("MarginPurchaseLimit", 0)),
                    short_sale_buy=int(row["ShortSaleBuy"]),
                    short_sale_sell=int(row["ShortSaleSell"]),
                    short_sale_cash_redemption=int(row.get("ShortSaleCashRedemption", 0)),
                    short_sale_balance=int(row["ShortSaleTodayBalance"]),
                    short_sale_quota=int(row.get("ShortSaleLimit", 0)),
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
