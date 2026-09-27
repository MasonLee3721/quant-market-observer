"""Price Normalizer Implementation."""

import json
from typing import Any, List, Optional

from qmo.models.price import DailyPrice
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
        results: List[DailyPrice] = []
        if not envelope.raw_body:
            return results

        try:
            payload = json.loads(envelope.raw_body)
        except Exception:
            return results

        if envelope.provider_name == "finmind":
            data = payload.get("data", []) if isinstance(payload, dict) else []
            for row in data:
                vol = int(row.get("Trading_Volume", 0))
                open_p = _parse_float(row.get("open"))
                high_p = _parse_float(row.get("max"))
                low_p = _parse_float(row.get("min"))
                close_p = _parse_float(row.get("close"))

                record = DailyPrice(
                    symbol=str(row.get("stock_id", envelope.params.get("data_id", ""))),
                    date=str(row.get("date", "")),
                    open_price=open_p,
                    high_price=high_p,
                    low_price=low_p,
                    close_price=close_p,
                    change=float(row["spread"]) if row.get("spread") is not None else None,
                    trading_volume=vol,
                    trading_value=int(row.get("Trading_money", 0)),
                    transaction_count=int(row.get("Trading_turnover", 0)),
                    no_trade=(vol == 0 or close_p is None),
                    source=envelope.provider_name,
                    retrieved_at=envelope.retrieved_at,
                )
                results.append(record)
        return results
