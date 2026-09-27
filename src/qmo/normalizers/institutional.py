"""Institutional Investor Flow Normalizer Implementation."""

import json
from typing import List

from qmo.models.institutional import InstitutionalFlow
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


class InstitutionalNormalizer:
    """Normalizes raw provider payload into standardized InstitutionalFlow models."""

    def normalize(self, envelope: RawResponseEnvelope) -> List[InstitutionalFlow]:
        """Convert raw payload envelope to a list of InstitutionalFlow instances."""
        if not envelope.raw_body:
            raise SchemaValidationError("Empty raw response body", provider=envelope.provider_name)

        try:
            payload = json.loads(envelope.raw_body)
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

            # Group rows by date
            by_date: dict[str, dict[str, int]] = {}
            for row in data:
                d = str(row.get("date", ""))
                if not d:
                    continue
                if d not in by_date:
                    by_date[d] = {}
                name = str(row.get("name", ""))
                buy = int(row.get("buy", 0))
                sell = int(row.get("sell", 0))

                if "Foreign" in name or "外資" in name:
                    by_date[d]["foreign_buy"] = buy
                    by_date[d]["foreign_sell"] = sell
                    by_date[d]["foreign_net"] = buy - sell
                elif "Investment" in name or "投信" in name:
                    by_date[d]["trust_buy"] = buy
                    by_date[d]["trust_sell"] = sell
                    by_date[d]["trust_net"] = buy - sell
                elif "Dealer" in name or "自營商" in name:
                    by_date[d]["dealer_buy"] = buy
                    by_date[d]["dealer_sell"] = sell
                    by_date[d]["dealer_net"] = buy - sell

            for d, flow in by_date.items():
                f_net = flow.get("foreign_net", 0)
                t_net = flow.get("trust_net", 0)
                d_net = flow.get("dealer_net", 0)
                record = InstitutionalFlow(
                    trade_date=d,
                    stock_id=str(envelope.params.get("data_id", "")),
                    foreign_buy=flow.get("foreign_buy", 0),
                    foreign_sell=flow.get("foreign_sell", 0),
                    foreign_net=f_net,
                    investment_trust_buy=flow.get("trust_buy", 0),
                    investment_trust_sell=flow.get("trust_sell", 0),
                    investment_trust_net=t_net,
                    dealer_buy=flow.get("dealer_buy", 0),
                    dealer_sell=flow.get("dealer_sell", 0),
                    dealer_net=d_net,
                    total_net=f_net + t_net + d_net,
                    source=envelope.provider_name,
                    retrieved_at=envelope.retrieved_at,
                )
                results.append(record)

        return results
