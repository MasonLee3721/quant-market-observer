"""Price Normalizer Implementation."""

import json
from typing import Any, List, Optional

from qmo.models.price import DailyPrice
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


def _parse_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


class PriceNormalizer:
    """Normalizes raw provider payload into standardized DailyPrice models."""

    def normalize(self, envelope: RawResponseEnvelope) -> List[DailyPrice]:
        """Convert raw payload envelope to a list of DailyPrice instances."""
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

        results: List[DailyPrice] = []

        if envelope.provider_name == "finmind":
            data = payload.get("data")
            if data is None or not isinstance(data, list):
                raise SchemaValidationError(
                    "FinMind payload missing 'data' list", provider=envelope.provider_name
                )

            for row in data:
                vol = int(row.get("Trading_Volume", 0))
                val = int(row.get("Trading_money", 0))
                open_p = _parse_float(row.get("open"))
                high_p = _parse_float(row.get("max"))
                low_p = _parse_float(row.get("min"))
                close_p = _parse_float(row.get("close"))

                # M0 Contract: no_trade is True if volume == 0 AND trading_value == 0
                is_no_trade = vol == 0 and val == 0

                q_flags: List[str] = []
                if is_no_trade:
                    q_flags.append("no_trade")
                if close_p is None and not is_no_trade:
                    q_flags.append("missing_price")

                record = DailyPrice(
                    trade_date=str(row.get("date", "")),
                    stock_id=str(row.get("stock_id", envelope.params.get("data_id", ""))),
                    market="TWSE",
                    open_price=open_p,
                    high_price=high_p,
                    low_price=low_p,
                    close_price=close_p,
                    change=float(row["spread"]) if row.get("spread") is not None else None,
                    trading_volume=vol,
                    trading_value=val,
                    transaction_count=int(row.get("Trading_turnover", 0)),
                    no_trade=is_no_trade,
                    source=envelope.provider_name,
                    retrieved_at=envelope.retrieved_at,
                    quality_flags=q_flags,
                )
                results.append(record)
        return results
