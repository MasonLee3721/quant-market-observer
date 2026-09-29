"""Institutional Investor Flow Normalizer Implementation."""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from qmo.models.institutional import InstitutionalFlow
from qmo.models.stock import StockMaster, load_universe_stock_master
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


def _official_trade_date(
    payload: Dict[str, Any], envelope: RawResponseEnvelope, provider: str
) -> str:
    resp_date: Optional[str] = None
    if payload.get("date"):
        raw_p = str(payload["date"]).strip()
        try:
            if re.fullmatch(r"\d{8}", raw_p):
                resp_date = datetime.strptime(raw_p, "%Y%m%d").strftime("%Y-%m-%d")
            elif re.fullmatch(r"\d{3}/\d{2}/\d{2}", raw_p):
                y, m, d = raw_p.split("/")
                resp_date = f"{int(y) + 1911:04d}-{m}-{d}"
            elif re.fullmatch(r"\d{7}", raw_p):
                y, m, d = raw_p[:3], raw_p[3:5], raw_p[5:7]
                resp_date = f"{int(y) + 1911:04d}-{m}-{d}"
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_p):
                resp_date = datetime.strptime(raw_p, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass

    if resp_date is None:
        tables = payload.get("tables")
        if isinstance(tables, list):
            for t in tables:
                if isinstance(t, dict) and "title" in t:
                    title = str(t["title"])
                    match = re.search(r"(\d{3})年(\d{2})月(\d{2})日", title)
                    if match:
                        y, m, d = match.group(1), match.group(2), match.group(3)
                        resp_date = f"{int(y) + 1911:04d}-{m}-{d}"
                        break

    if resp_date is None:
        raise SchemaValidationError(
            f"Official {provider.upper()} response missing official trade date in payload",
            provider=provider,
        )

    req_raw = envelope.params.get("date") or envelope.params.get("d")
    if req_raw:
        req_str = str(req_raw).strip()
        req_date: Optional[str] = None
        try:
            if re.fullmatch(r"\d{8}", req_str):
                req_date = datetime.strptime(req_str, "%Y%m%d").strftime("%Y-%m-%d")
            elif re.fullmatch(r"\d{3}/\d{2}/\d{2}", req_str):
                y, m, d = req_str.split("/")
                req_date = f"{int(y) + 1911:04d}-{m}-{d}"
            elif re.fullmatch(r"\d{7}", req_str):
                y, m, d = req_str[:3], req_str[3:5], req_str[5:7]
                req_date = f"{int(y) + 1911:04d}-{m}-{d}"
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", req_str):
                req_date = datetime.strptime(req_str, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass

        if req_date and resp_date != req_date:
            raise SchemaValidationError(
                f"Official {provider.upper()} response date '{resp_date}' does not match "
                f"requested date '{req_date}'",
                provider=provider,
            )

    return resp_date


def _official_int(val: Any, field: str, provider: str) -> int:
    text = str(val).strip().replace(",", "")
    if text in {"", "-", "--", "---", "None"}:
        return 0
    try:
        return int(text)
    except (ValueError, TypeError) as exc:
        raise SchemaValidationError(
            f"Invalid official numeric field '{field}': {val}", provider=provider
        ) from exc


class InstitutionalNormalizer:
    """Normalizes raw provider payload into standardized InstitutionalFlow models."""

    def __init__(self, stock_master: Optional[Dict[str, StockMaster]] = None) -> None:
        self.stock_master = stock_master

    def get_stock_market(self, stock_id: str) -> str:
        """Lookup market for stock_id from injected StockMaster registry."""
        registry = (
            self.stock_master if self.stock_master is not None else load_universe_stock_master()
        )
        if stock_id in registry:
            return registry[stock_id].market
        raise SchemaValidationError(
            f"Unknown stock_id '{stock_id}' not found in StockMaster registry",
            provider="normalizer",
        )

    def normalize(self, envelope: RawResponseEnvelope) -> List[InstitutionalFlow]:
        """Convert raw payload envelope to a list of InstitutionalFlow instances."""
        if envelope.provider_name in {"twse", "tpex"}:
            return self._normalize_official_market(envelope)

        if envelope.provider_name != "finmind":
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

        data = payload.get("data")
        if data is None or not isinstance(data, list):
            raise SchemaValidationError(
                "FinMind payload missing 'data' list", provider=envelope.provider_name
            )

        results: List[InstitutionalFlow] = []

        try:
            by_date: Dict[Tuple[str, str], Dict[str, Any]] = {}
            for row in data:
                if not isinstance(row, dict):
                    raise SchemaValidationError(
                        "Row item is not a dictionary", provider=envelope.provider_name
                    )

                stock_id_row = str(row.get("stock_id", envelope.params.get("data_id", "")))
                if not stock_id_row:
                    raise SchemaValidationError(
                        "Institutional row missing stock_id and envelope params missing data_id",
                        provider=envelope.provider_name,
                    )

                d = str(row.get("date", ""))
                if not d:
                    raise SchemaValidationError(
                        "Institutional row missing required field 'date'",
                        provider=envelope.provider_name,
                    )

                key_tuple = (stock_id_row, d)
                if key_tuple not in by_date:
                    by_date[key_tuple] = {
                        "foreign_buy": 0,
                        "foreign_sell": 0,
                        "trust_buy": 0,
                        "trust_sell": 0,
                        "dealer_buy": 0,
                        "dealer_sell": 0,
                        "categories": set(),
                    }
                name = str(row.get("name", ""))
                if name:
                    by_date[key_tuple]["categories"].add(name)

                if (
                    "buy" not in row
                    or row["buy"] is None
                    or "sell" not in row
                    or row["sell"] is None
                ):
                    raise SchemaValidationError(
                        "Institutional row missing required field 'buy' or 'sell'",
                        provider=envelope.provider_name,
                    )
                try:
                    buy = int(row["buy"])
                    sell = int(row["sell"])
                except (ValueError, TypeError) as e:
                    raise SchemaValidationError(
                        f"Invalid integer for institutional buy/sell: {e}",
                        provider=envelope.provider_name,
                    ) from e

                if "Foreign" in name or "外資" in name:
                    by_date[key_tuple]["foreign_buy"] += buy
                    by_date[key_tuple]["foreign_sell"] += sell
                elif "Investment" in name or "投信" in name:
                    by_date[key_tuple]["trust_buy"] += buy
                    by_date[key_tuple]["trust_sell"] += sell
                elif "Dealer" in name or "自營商" in name:
                    by_date[key_tuple]["dealer_buy"] += buy
                    by_date[key_tuple]["dealer_sell"] += sell

            for (stock_id, d), flow in by_date.items():
                market = self.get_stock_market(stock_id)

                f_buy = flow["foreign_buy"]
                f_sell = flow["foreign_sell"]
                f_net = f_buy - f_sell

                t_buy = flow["trust_buy"]
                t_sell = flow["trust_sell"]
                t_net = t_buy - t_sell

                d_buy = flow["dealer_buy"]
                d_sell = flow["dealer_sell"]
                d_net = d_buy - d_sell

                cats_str = "|".join(sorted(list(flow["categories"])))
                src_str = (
                    "FinMind:TaiwanStockInstitutionalInvestorsBuySell"
                    if envelope.provider_name == "finmind"
                    else envelope.provider_name
                )

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
                    categories=cats_str,
                    source=src_str,
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

    def _normalize_official_market(self, envelope: RawResponseEnvelope) -> List[InstitutionalFlow]:
        """Normalize official TWSE/TPEx market-wide daily institutional response."""
        provider = envelope.provider_name
        if envelope.status_code != 200 or not envelope.raw_body_bytes:
            raise SchemaValidationError(
                "Official market response is unavailable", provider=provider
            )
        try:
            payload = json.loads(envelope.raw_body_str)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SchemaValidationError(
                f"Failed to parse JSON body: {exc}", provider=provider
            ) from exc

        if not isinstance(payload, dict) or payload.get("stat") not in {"OK", "ok"}:
            raise SchemaValidationError("Official payload status is not OK", provider=provider)

        trade_date = _official_trade_date(payload, envelope, provider)
        results: List[InstitutionalFlow] = []

        if provider == "twse":
            required = {
                "證券代號",
                "外陸資買進股數(不含外資自營商)",
                "外陸資賣出股數(不含外資自營商)",
                "外資自營商買進股數",
                "外資自營商賣出股數",
                "投信買進股數",
                "投信賣出股數",
                "自營商買進股數(自行買賣)",
                "自營商賣出股數(自行買賣)",
                "自營商買進股數(避險)",
                "自營商賣出股數(避險)",
                "三大法人買賣超股數",
            }
            fields, data_rows = self._extract_twse_table(payload, required, provider)
            for values in data_rows:
                if not isinstance(values, list) or len(values) != len(fields):
                    raise SchemaValidationError(
                        "Official institutional row width mismatch", provider=provider
                    )
                row = dict(zip(fields, values, strict=True))
                sid = str(row["證券代號"]).strip()
                if self.stock_master is not None:
                    stock = self.stock_master.get(sid)
                    if stock is None or stock.market != "TWSE":
                        continue
                else:
                    if not re.fullmatch(r"\d{4}", sid) or sid.startswith(("00", "91")):
                        continue

                f_buy = _official_int(
                    row.get("外陸資買進股數(不含外資自營商)"), "foreign_buy_1", provider
                ) + _official_int(row.get("外資自營商買進股數"), "foreign_buy_2", provider)
                f_sell = _official_int(
                    row.get("外陸資賣出股數(不含外資自營商)"), "foreign_sell_1", provider
                ) + _official_int(row.get("外資自營商賣出股數"), "foreign_sell_2", provider)
                f_net = f_buy - f_sell

                t_buy = _official_int(row.get("投信買進股數"), "trust_buy", provider)
                t_sell = _official_int(row.get("投信賣出股數"), "trust_sell", provider)
                t_net = t_buy - t_sell

                d_buy = _official_int(
                    row.get("自營商買進股數(自行買賣)"), "dealer_buy_1", provider
                ) + _official_int(row.get("自營商買進股數(避險)"), "dealer_buy_2", provider)
                d_sell = _official_int(
                    row.get("自營商賣出股數(自行買賣)"), "dealer_sell_1", provider
                ) + _official_int(row.get("自營商賣出股數(避險)"), "dealer_sell_2", provider)
                d_net = d_buy - d_sell

                total_net = f_net + t_net + d_net

                results.append(
                    InstitutionalFlow(
                        trade_date=trade_date,
                        stock_id=sid,
                        market="TWSE",
                        foreign_buy=f_buy,
                        foreign_sell=f_sell,
                        foreign_net=f_net,
                        investment_trust_buy=t_buy,
                        investment_trust_sell=t_sell,
                        investment_trust_net=t_net,
                        dealer_buy=d_buy,
                        dealer_sell=d_sell,
                        dealer_net=d_net,
                        total_net=total_net,
                        categories="Foreign|InvestmentTrust|Dealer",
                        source="TWSE:fund/T86",
                        retrieved_at=envelope.retrieved_at,
                    )
                )
        else:
            table = self._extract_tpex_table(payload, provider)
            data_rows = table.get("data", [])
            for values in data_rows:
                if not isinstance(values, list) or len(values) < 24:
                    raise SchemaValidationError(
                        "Official TPEx institutional row width mismatch", provider=provider
                    )
                sid = str(values[0]).strip()
                if self.stock_master is not None:
                    stock = self.stock_master.get(sid)
                    if stock is None or stock.market != "TPEx":
                        continue
                else:
                    if not re.fullmatch(r"\d{4}", sid) or sid.startswith(("00", "91")):
                        continue

                f_buy = _official_int(values[8], "foreign_buy", provider)
                f_sell = _official_int(values[9], "foreign_sell", provider)
                f_net = f_buy - f_sell

                t_buy = _official_int(values[11], "trust_buy", provider)
                t_sell = _official_int(values[12], "trust_sell", provider)
                t_net = t_buy - t_sell

                d_buy = _official_int(values[20], "dealer_buy", provider)
                d_sell = _official_int(values[21], "dealer_sell", provider)
                d_net = d_buy - d_sell

                tot_net = _official_int(values[23], "total_net", provider)

                results.append(
                    InstitutionalFlow(
                        trade_date=trade_date,
                        stock_id=sid,
                        market="TPEx",
                        foreign_buy=f_buy,
                        foreign_sell=f_sell,
                        foreign_net=f_net,
                        investment_trust_buy=t_buy,
                        investment_trust_sell=t_sell,
                        investment_trust_net=t_net,
                        dealer_buy=d_buy,
                        dealer_sell=d_sell,
                        dealer_net=d_net,
                        total_net=tot_net,
                        categories="Foreign|InvestmentTrust|Dealer",
                        source="TPEx:insti/dailyTrade",
                        retrieved_at=envelope.retrieved_at,
                    )
                )

        if not results:
            raise SchemaValidationError(
                "Official market table contained no stocks from the active universe",
                provider=provider,
            )
        return results

    @staticmethod
    def _extract_twse_table(
        payload: Dict[str, Any], required: set[str], provider: str
    ) -> Tuple[List[str], List[Any]]:
        fields = payload.get("fields")
        data = payload.get("data")
        if isinstance(fields, list) and required.issubset(set(fields)) and isinstance(data, list):
            return fields, data

        tables = payload.get("tables")
        if isinstance(tables, list):
            for t in tables:
                if not isinstance(t, dict):
                    continue
                tf = t.get("fields")
                td = t.get("data")
                if isinstance(tf, list) and required.issubset(set(tf)) and isinstance(td, list):
                    return tf, td
        raise SchemaValidationError(
            "Official TWSE institutional table not found", provider=provider
        )

    @staticmethod
    def _extract_tpex_table(payload: Dict[str, Any], provider: str) -> Dict[str, Any]:
        tables = payload.get("tables")
        if isinstance(tables, list):
            for t in tables:
                if not isinstance(t, dict):
                    continue
                tf = t.get("fields")
                td = t.get("data")
                if (
                    isinstance(tf, list)
                    and len(tf) >= 24
                    and isinstance(td, list)
                    and (t.get("title") == "三大法人買賣明細資訊" or tf[0] in {"代號", "證券代號"})
                ):
                    return t
        raise SchemaValidationError(
            "Official TPEx institutional table not found", provider=provider
        )
