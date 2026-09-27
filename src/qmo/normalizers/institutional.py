"""Institutional Investor Flow Normalizer Implementation."""

import json
from typing import Dict, List

from qmo.models.institutional import InstitutionalFlow
from qmo.normalizers.price import get_stock_market
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


class InstitutionalNormalizer:
    """Normalizes raw provider payload into standardized InstitutionalFlow models."""

    def normalize(self, envelope: RawResponseEnvelope) -> List[InstitutionalFlow]:
        """Convert raw payload envelope to a list of InstitutionalFlow instances."""
        if envelope.provider_name not in ["finmind", "twse", "tpex"]:
            raise SchemaValidationError(
                f"Unsupported provider for InstitutionalNormalizer: {envelope.provider_name}",
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

        results: List[InstitutionalFlow] = []

        if envelope.provider_name == "finmind":
            data = payload.get("data")
            if data is None or not isinstance(data, list):
                raise SchemaValidationError(
                    "FinMind payload missing 'data' list", provider=envelope.provider_name
                )

            # Group and accumulate rows by date
            by_date: Dict[str, Dict[str, int]] = {}
            for row in data:
                d = str(row.get("date", ""))
                if not d:
                    continue
                if d not in by_date:
                    by_date[d] = {
                        "foreign_buy": 0,
                        "foreign_sell": 0,
                        "trust_buy": 0,
                        "trust_sell": 0,
                        "dealer_buy": 0,
                        "dealer_sell": 0,
                    }
                name = str(row.get("name", ""))
                buy = int(row.get("buy", 0))
                sell = int(row.get("sell", 0))

                # Accumulate foreign investors (Foreign_Investor, Foreign_Dealer_Self)
                if "Foreign" in name or "外資" in name:
                    by_date[d]["foreign_buy"] += buy
                    by_date[d]["foreign_sell"] += sell
                # Accumulate investment trusts
                elif "Investment" in name or "投信" in name:
                    by_date[d]["trust_buy"] += buy
                    by_date[d]["trust_sell"] += sell
                # Accumulate dealers (Dealer_Self, Dealer_Hedging)
                elif "Dealer" in name or "自營商" in name:
                    by_date[d]["dealer_buy"] += buy
                    by_date[d]["dealer_sell"] += sell

            stock_id = str(envelope.params.get("data_id", ""))
            market = get_stock_market(stock_id)

            for d, flow in by_date.items():
                f_buy = flow["foreign_buy"]
                f_sell = flow["foreign_sell"]
                f_net = f_buy - f_sell

                t_buy = flow["trust_buy"]
                t_sell = flow["trust_sell"]
                t_net = t_buy - t_sell

                d_buy = flow["dealer_buy"]
                d_sell = flow["dealer_sell"]
                d_net = d_buy - d_sell

                record = InstitutionalFlow(
                    trade_date=d,
                    stock_id=stock_id,
                    market=market,
                    foreign_buy=f_buy,
                    foreign_sell=f_sell,
                    foreign_net=f_net,
                    investment_trust_buy=t_buy,
                    investment_trust_sell=t_sell,
                    investment_trust_net=t_net,
                    dealer_buy=d_buy,
                    dealer_sell=d_sell,
                    dealer_net=d_net,
                    total_net=f_net + t_net + d_net,
                    source=envelope.provider_name,
                    retrieved_at=envelope.retrieved_at,
                )
                results.append(record)

        return results
