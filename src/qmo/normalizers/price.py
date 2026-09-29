"""Price Normalizer Implementation."""

import json
import re
from datetime import datetime
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

    def normalize(self, envelope: RawResponseEnvelope) -> List[DailyPrice]:
        """Convert raw payload envelope to a list of DailyPrice instances."""
        if envelope.provider_name in {"twse", "tpex"}:
            return self._normalize_official_market(envelope)

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

                src_str = (
                    "FinMind:TaiwanStockPrice"
                    if envelope.provider_name == "finmind"
                    else envelope.provider_name
                )
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
                    source=src_str,
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

    def _normalize_official_market(self, envelope: RawResponseEnvelope) -> List[DailyPrice]:
        """Normalize one official TWSE/TPEx market-wide daily quote response."""
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
        required = (
            {"證券代號", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"}
            if provider == "twse"
            else {"代號", "成交股數", "成交金額(元)", "成交筆數", "開盤", "最高", "最低", "收盤"}
        )
        table = self._find_official_table(payload, required, provider)
        fields = table["fields"]
        trade_date = self._official_trade_date(payload, envelope, provider)
        results: List[DailyPrice] = []
        for values in table["data"]:
            if not isinstance(values, list) or len(values) != len(fields):
                raise SchemaValidationError("Official quote row width mismatch", provider=provider)
            row = dict(zip(fields, values, strict=True))
            sid = str(row["證券代號" if provider == "twse" else "代號"]).strip()
            expected_market = "TWSE" if provider == "twse" else "TPEx"
            if self.stock_master is not None:
                stock = self.stock_master.get(sid)
                if stock is None or stock.market != expected_market:
                    continue
            else:
                if not re.fullmatch(r"\d{4}", sid) or sid.startswith(("00", "91")):
                    continue
            results.append(self._official_price_row(row, envelope, trade_date, sid, provider))
        if not results:
            raise SchemaValidationError(
                "Official market table contained no stocks from the active universe",
                provider=provider,
            )
        return results

    @staticmethod
    def _find_official_table(
        payload: Dict[str, Any], required: set[str], provider: str
    ) -> Dict[str, Any]:
        tables = payload.get("tables")
        if not isinstance(tables, list):
            raise SchemaValidationError("Official payload missing tables list", provider=provider)
        for table in tables:
            if not isinstance(table, dict):
                continue
            fields, data = table.get("fields"), table.get("data")
            if (
                isinstance(fields, list)
                and required.issubset(set(fields))
                and isinstance(data, list)
            ):
                return table
        raise SchemaValidationError("Official daily quote table not found", provider=provider)

    @staticmethod
    def _official_trade_date(
        payload: Dict[str, Any], envelope: RawResponseEnvelope, provider: str
    ) -> str:
        raw = str(
            envelope.params.get("date")
            or envelope.params.get("d")
            or payload.get("date")
            or ""
        )
        try:
            if re.fullmatch(r"\d{8}", raw):
                return datetime.strptime(raw, "%Y%m%d").strftime("%Y-%m-%d")
            if re.fullmatch(r"\d{3}/\d{2}/\d{2}", raw):
                year, month, day = raw.split("/")
                return f"{int(year) + 1911:04d}-{month}-{day}"
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError as exc:
            raise SchemaValidationError(
                f"Invalid official trade date: {raw}", provider=provider
            ) from exc

    @staticmethod
    def _official_number(value: Any, field: str, provider: str, *, integer: bool = False) -> Any:
        text = str(value).strip().replace(",", "")
        if text in {"", "-", "--", "---", "None"}:
            return None
        try:
            return int(text) if integer else float(text)
        except ValueError as exc:
            raise SchemaValidationError(
                f"Invalid official numeric field '{field}': {value}", provider=provider
            ) from exc

    def _official_price_row(
        self,
        row: Dict[str, Any],
        envelope: RawResponseEnvelope,
        trade_date: str,
        sid: str,
        provider: str,
    ) -> DailyPrice:
        if provider == "twse":
            names = {
                "open": "開盤價",
                "high": "最高價",
                "low": "最低價",
                "close": "收盤價",
                "volume": "成交股數",
                "value": "成交金額",
                "count": "成交筆數",
            }
            delta = self._official_number(row.get("漲跌價差"), "漲跌價差", provider)
            sign = re.sub(r"<[^>]+>", "", str(row.get("漲跌(+/-)", ""))).strip()
            change = -abs(delta) if delta is not None and "-" in sign else delta
            source = "TWSE:MI_INDEX"
        else:
            names = {
                "open": "開盤",
                "high": "最高",
                "low": "最低",
                "close": "收盤",
                "volume": "成交股數",
                "value": "成交金額(元)",
                "count": "成交筆數",
            }
            change = self._official_number(row.get("漲跌"), "漲跌", provider)
            source = "TPEx:daily_close_quotes"
        volume = self._official_number(
            row.get(names["volume"]), names["volume"], provider, integer=True
        )
        value = self._official_number(
            row.get(names["value"]), names["value"], provider, integer=True
        )
        count = self._official_number(
            row.get(names["count"]), names["count"], provider, integer=True
        )
        if volume is None or value is None or count is None:
            raise SchemaValidationError(
                "Official quote row missing volume/value/count", provider=provider
            )
        return DailyPrice(
            trade_date=trade_date,
            stock_id=sid,
            market="TWSE" if provider == "twse" else "TPEx",
            open_price=self._official_number(row.get(names["open"]), names["open"], provider),
            high_price=self._official_number(row.get(names["high"]), names["high"], provider),
            low_price=self._official_number(row.get(names["low"]), names["low"], provider),
            close_price=self._official_number(row.get(names["close"]), names["close"], provider),
            change=change,
            trading_volume=volume,
            trading_value=value,
            transaction_count=count,
            no_trade=volume == 0 and value == 0,
            source=source,
            retrieved_at=envelope.retrieved_at,
        )
