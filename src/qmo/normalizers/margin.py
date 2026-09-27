"""Margin Trading Normalizer Implementation."""

import json
from typing import List

from qmo.models.margin import Margin
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


class MarginNormalizer:
    """Normalizes raw provider payload into standardized Margin models."""

    def normalize(self, envelope: RawResponseEnvelope) -> List[Margin]:
        """Convert raw payload envelope to a list of Margin instances."""
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

        results: List[Margin] = []

        if envelope.provider_name == "finmind":
            data = payload.get("data")
            if data is None or not isinstance(data, list):
                raise SchemaValidationError(
                    "FinMind payload missing 'data' list", provider=envelope.provider_name
                )

            for row in data:
                record = Margin(
                    trade_date=str(row.get("date", "")),
                    stock_id=str(row.get("stock_id", envelope.params.get("data_id", ""))),
                    margin_purchase_buy=int(row.get("MarginPurchaseBuy", 0)),
                    margin_purchase_sell=int(row.get("MarginPurchaseSell", 0)),
                    margin_purchase_cash_redemption=int(row.get("MarginPurchaseCashRedemption", 0)),
                    margin_purchase_balance=int(row.get("MarginPurchaseTodayBalance", 0)),
                    margin_purchase_quota=int(row.get("MarginPurchaseLimit", 0)),
                    short_sale_buy=int(row.get("ShortSaleBuy", 0)),
                    short_sale_sell=int(row.get("ShortSaleSell", 0)),
                    short_sale_cash_redemption=int(row.get("ShortSaleCashRedemption", 0)),
                    short_sale_balance=int(row.get("ShortSaleTodayBalance", 0)),
                    short_sale_quota=int(row.get("ShortSaleLimit", 0)),
                    source=envelope.provider_name,
                    retrieved_at=envelope.retrieved_at,
                )
                results.append(record)

        return results
