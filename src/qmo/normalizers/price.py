"""Price Normalizer Implementation."""

import json
from typing import Any, Dict, List, Optional

from qmo.models.price import DailyPrice
from qmo.models.stock import StockMaster, load_universe_stock_master
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


def _parse_positive_float(val: Any, field_name: str, provider: str) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError) as e:
        raise SchemaValidationError(
            f"Invalid numeric value for field '{field_name}': {val}", provider=provider
        ) from e


def _parse_spread_float(val: Any, field_name: str, provider: str) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError) as e:
        raise SchemaValidationError(
            f"Invalid numeric value for field '{field_name}': {val}", provider=provider
        ) from e


class PriceNormalizer:
    """Normalizes raw provider payload into standardized DailyPrice models."""

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

    def normalize(self, envelope: RawResponseEnvelope) -> List[DailyPrice]:
        """Convert raw payload envelope to a list of DailyPrice instances."""
        if envelope.provider_name in ["twse", "tpex"]:
            raise SchemaValidationError(
                f"Normalizer for provider '{envelope.provider_name}' not yet implemented",
                provider=envelope.provider_name,
            )

        if envelope.provider_name != "finmind":
            raise SchemaValidationError(
                f"Unsupported provider for PriceNormalizer: {envelope.provider_name}",
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

        results: List[DailyPrice] = []

        try:
            for row in data:
                if not isinstance(row, dict):
                    raise SchemaValidationError(
                        "Row item is not a dictionary", provider=envelope.provider_name
                    )

                stock_id = str(row.get("stock_id", envelope.params.get("data_id", "")))
                market = self.get_stock_market(stock_id)

                if "Trading_Volume" not in row or row["Trading_Volume"] is None:
                    raise SchemaValidationError(
                        "Row missing required field 'Trading_Volume'",
                        provider=envelope.provider_name,
                    )
                if "Trading_money" not in row or row["Trading_money"] is None:
                    raise SchemaValidationError(
                        "Row missing required field 'Trading_money'",
                        provider=envelope.provider_name,
                    )

                try:
                    vol = int(row["Trading_Volume"])
                    val = int(row["Trading_money"])
                except (ValueError, TypeError) as e:
                    raise SchemaValidationError(
                        f"Invalid integer for Trading_Volume/Trading_money: {e}",
                        provider=envelope.provider_name,
                    ) from e

                open_p = _parse_positive_float(row.get("open"), "open", envelope.provider_name)
                high_p = _parse_positive_float(row.get("max"), "max", envelope.provider_name)
                low_p = _parse_positive_float(row.get("min"), "min", envelope.provider_name)
                close_p = _parse_positive_float(row.get("close"), "close", envelope.provider_name)

                # M0 Contract: no_trade is True if volume == 0 AND trading_value == 0
                is_no_trade = vol == 0 and val == 0

                q_flags: List[str] = []
                if is_no_trade:
                    q_flags.append("no_trade")
                if close_p is None and not is_no_trade:
                    q_flags.append("missing_price")

                record = DailyPrice(
                    trade_date=str(row.get("date", "")),
                    stock_id=stock_id,
                    market=market,
                    open_price=open_p,
                    high_price=high_p,
                    low_price=low_p,
                    close_price=close_p,
                    change=_parse_spread_float(row.get("spread"), "spread", envelope.provider_name),
                    trading_volume=vol,
                    trading_value=val,
                    transaction_count=int(row.get("Trading_turnover", 0)),
                    no_trade=is_no_trade,
                    source=envelope.provider_name,
                    retrieved_at=envelope.retrieved_at,
                    quality_flags=q_flags,
                )
                results.append(record)
        except SchemaValidationError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            raise SchemaValidationError(
                f"Schema drift or row parsing failure: {e}", provider=envelope.provider_name
            ) from e

        return results
