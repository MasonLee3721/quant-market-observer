"""Margin Trading Normalizer Implementation."""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from qmo.models.margin import Margin
from qmo.models.stock import StockMaster, load_universe_stock_master
from qmo.providers.exceptions import SchemaValidationError
from qmo.providers.protocols import RawResponseEnvelope


def _official_trade_date(
    payload: Dict[str, Any], envelope: RawResponseEnvelope, provider: str
) -> str:
    raw = str(
        envelope.params.get("date") or envelope.params.get("d") or payload.get("date") or ""
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


def _resolve_twse_margin_column_indices(fields: List[str]) -> Dict[str, Optional[int]]:
    """Dynamically resolve TWSE MI_MARGN column indices for Margin Purchase and Short Sale."""
    fields_clean = [str(f).strip() for f in fields]
    buy_idxs = [i for i, f in enumerate(fields_clean) if f == "買進"]
    sell_idxs = [i for i, f in enumerate(fields_clean) if f == "賣出"]
    red_mp_idxs = [i for i, f in enumerate(fields_clean) if "現金" in f or "償還" in f]
    red_ss_idxs = [i for i, f in enumerate(fields_clean) if "現券" in f or "償還" in f]
    prev_idxs = [i for i, f in enumerate(fields_clean) if "前日" in f]
    today_idxs = [i for i, f in enumerate(fields_clean) if "今日" in f]
    limit_idxs = [i for i, f in enumerate(fields_clean) if "限額" in f]
    offset_idxs = [i for i, f in enumerate(fields_clean) if "資券" in f]
    note_idxs = [i for i, f in enumerate(fields_clean) if "註記" in f]

    if len(buy_idxs) < 2 or len(sell_idxs) < 2 or len(prev_idxs) < 2 or len(today_idxs) < 2:
        raise SchemaValidationError(
            "Missing required duplicate headers in TWSE MI_MARGN table",
            provider="twse",
        )
    if not red_mp_idxs or not red_ss_idxs or len(limit_idxs) < 2 or not offset_idxs:
        raise SchemaValidationError(
            "Missing required column headers in TWSE MI_MARGN table",
            provider="twse",
        )

    return {
        "sid": 0,
        "mp_buy": buy_idxs[0],
        "mp_sell": sell_idxs[0],
        "mp_red": red_mp_idxs[0],
        "mp_prev": prev_idxs[0],
        "mp_bal": today_idxs[0],
        "mp_quota": limit_idxs[0],
        "ss_buy": buy_idxs[1],
        "ss_sell": sell_idxs[1],
        "ss_red": red_ss_idxs[1] if len(red_ss_idxs) > 1 else red_ss_idxs[0],
        "ss_prev": prev_idxs[1],
        "ss_bal": today_idxs[1],
        "ss_quota": limit_idxs[1],
        "offset": offset_idxs[0],
        "note": note_idxs[0] if note_idxs else None,
    }


class MarginNormalizer:
    """Normalizes raw provider payload into standardized Margin models."""

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

    def normalize(self, envelope: RawResponseEnvelope) -> List[Margin]:
        """Convert raw payload envelope to a list of Margin instances."""
        if envelope.provider_name in {"twse", "tpex"}:
            return self._normalize_official_market(envelope)

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

                    mp_prev_raw = row.get("MarginPurchaseYesterdayBalance")
                    mp_prev = int(mp_prev_raw) if mp_prev_raw is not None else None

                    ss_buy = int(row["ShortSaleBuy"])
                    ss_sell = int(row["ShortSaleSell"])
                    ss_red = int(ss_red_val)
                    ss_bal = int(row["ShortSaleTodayBalance"])
                    ss_limit = int(row["ShortSaleLimit"])

                    ss_prev_raw = row.get("ShortSaleYesterdayBalance")
                    ss_prev = int(ss_prev_raw) if ss_prev_raw is not None else None

                    offset_raw = row.get("OffsetLoanAndShort")
                    offset_val = int(offset_raw) if offset_raw is not None else None

                    note_raw = row.get("Note")
                    note_val = str(note_raw).strip() if note_raw is not None else None
                except (ValueError, TypeError) as e:
                    raise SchemaValidationError(
                        f"Invalid integer value in margin field: {e}",
                        provider=envelope.provider_name,
                    ) from e

                src_str = (
                    "FinMind:TaiwanStockMarginPurchaseShortSale"
                    if envelope.provider_name == "finmind"
                    else envelope.provider_name
                )

                record = Margin(
                    trade_date=str(row.get("date", "")),
                    stock_id=stock_id,
                    market=market,
                    margin_purchase_buy=mp_buy,
                    margin_purchase_sell=mp_sell,
                    margin_purchase_cash_redemption=mp_red,
                    margin_purchase_balance=mp_bal,
                    margin_purchase_previous_balance=mp_prev,
                    margin_purchase_quota=mp_limit,
                    short_sale_buy=ss_buy,
                    short_sale_sell=ss_sell,
                    short_sale_cash_redemption=ss_red,
                    short_sale_balance=ss_bal,
                    short_sale_previous_balance=ss_prev,
                    short_sale_quota=ss_limit,
                    offset_loan_and_short=offset_val,
                    note=note_val,
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

    def _normalize_official_market(self, envelope: RawResponseEnvelope) -> List[Margin]:
        """Normalize official TWSE/TPEx market-wide daily margin trading response."""
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
        results: List[Margin] = []

        if provider == "twse":
            required = {"代號", "前日餘額", "資券互抵"}
            table = self._extract_twse_table(payload, required, provider)
            fields = table.get("fields", [])
            data_rows = table.get("data", [])
            col_map = _resolve_twse_margin_column_indices(fields)

            def _get_val(row_vals: List[Any], col_key: str) -> Any:
                idx = col_map.get(col_key)
                if idx is not None and idx < len(row_vals):
                    return row_vals[idx]
                return None

            for values in data_rows:
                if not isinstance(values, list) or len(values) < 15:
                    raise SchemaValidationError(
                        "Official TWSE margin row width mismatch", provider=provider
                    )

                sid = str(_get_val(values, "sid") or values[0]).strip()
                if self.stock_master is not None:
                    stock = self.stock_master.get(sid)
                    if stock is None or stock.market != "TWSE":
                        continue
                else:
                    if not re.fullmatch(r"\d{4}", sid) or sid.startswith(("00", "91")):
                        continue

                mp_buy = _official_int(_get_val(values, "mp_buy"), "mp_buy", provider)
                mp_sell = _official_int(_get_val(values, "mp_sell"), "mp_sell", provider)
                mp_red = _official_int(_get_val(values, "mp_red"), "mp_red", provider)
                mp_prev = _official_int(_get_val(values, "mp_prev"), "mp_prev", provider)
                mp_bal = _official_int(_get_val(values, "mp_bal"), "mp_bal", provider)
                mp_quota = _official_int(_get_val(values, "mp_quota"), "mp_quota", provider)

                ss_buy = _official_int(_get_val(values, "ss_buy"), "ss_buy", provider)
                ss_sell = _official_int(_get_val(values, "ss_sell"), "ss_sell", provider)
                ss_red = _official_int(_get_val(values, "ss_red"), "ss_red", provider)
                ss_prev = _official_int(_get_val(values, "ss_prev"), "ss_prev", provider)
                ss_bal = _official_int(_get_val(values, "ss_bal"), "ss_bal", provider)
                ss_quota = _official_int(_get_val(values, "ss_quota"), "ss_quota", provider)
                offset = _official_int(_get_val(values, "offset"), "offset", provider)
                note_raw = _get_val(values, "note")
                note = str(note_raw).strip() if note_raw else None

                results.append(
                    Margin(
                        trade_date=trade_date,
                        stock_id=sid,
                        market="TWSE",
                        margin_purchase_buy=mp_buy,
                        margin_purchase_sell=mp_sell,
                        margin_purchase_cash_redemption=mp_red,
                        margin_purchase_balance=mp_bal,
                        margin_purchase_previous_balance=mp_prev,
                        margin_purchase_quota=mp_quota,
                        short_sale_buy=ss_buy,
                        short_sale_sell=ss_sell,
                        short_sale_cash_redemption=ss_red,
                        short_sale_balance=ss_bal,
                        short_sale_previous_balance=ss_prev,
                        short_sale_quota=ss_quota,
                        offset_loan_and_short=offset,
                        note=note,
                        source="TWSE:marginTrading/MI_MARGN",
                        retrieved_at=envelope.retrieved_at,
                    )
                )
        else:
            table = self._extract_tpex_table(payload, provider)
            data_rows = table.get("data", [])
            for values in data_rows:
                if not isinstance(values, list) or len(values) < 20:
                    raise SchemaValidationError(
                        "Official TPEx margin row width mismatch", provider=provider
                    )
                sid = str(values[0]).strip()
                if self.stock_master is not None:
                    stock = self.stock_master.get(sid)
                    if stock is None or stock.market != "TPEx":
                        continue
                else:
                    if not re.fullmatch(r"\d{4}", sid) or sid.startswith(("00", "91")):
                        continue

                mp_prev = _official_int(values[2], "mp_prev", provider)
                mp_buy = _official_int(values[3], "mp_buy", provider)
                mp_sell = _official_int(values[4], "mp_sell", provider)
                mp_red = _official_int(values[5], "mp_red", provider)
                mp_bal = _official_int(values[6], "mp_bal", provider)
                mp_quota = _official_int(values[9], "mp_quota", provider)

                ss_prev = _official_int(values[10], "ss_prev", provider)
                ss_sell = _official_int(values[11], "ss_sell", provider)
                ss_buy = _official_int(values[12], "ss_buy", provider)
                ss_red = _official_int(values[13], "ss_red", provider)
                ss_bal = _official_int(values[14], "ss_bal", provider)
                ss_quota = _official_int(values[17], "ss_quota", provider)
                offset = _official_int(values[18], "offset", provider)
                note = str(values[19]).strip() if len(values) > 19 and values[19] else None

                results.append(
                    Margin(
                        trade_date=trade_date,
                        stock_id=sid,
                        market="TPEx",
                        margin_purchase_buy=mp_buy,
                        margin_purchase_sell=mp_sell,
                        margin_purchase_cash_redemption=mp_red,
                        margin_purchase_balance=mp_bal,
                        margin_purchase_previous_balance=mp_prev,
                        margin_purchase_quota=mp_quota,
                        short_sale_buy=ss_buy,
                        short_sale_sell=ss_sell,
                        short_sale_cash_redemption=ss_red,
                        short_sale_balance=ss_bal,
                        short_sale_previous_balance=ss_prev,
                        short_sale_quota=ss_quota,
                        offset_loan_and_short=offset,
                        note=note,
                        source="TPEx:margin/balance",
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
    ) -> Dict[str, Any]:
        tables = payload.get("tables")
        if isinstance(tables, list):
            for t in tables:
                if not isinstance(t, dict):
                    continue
                tf = t.get("fields")
                td = t.get("data")
                title = str(t.get("title", ""))
                if (
                    isinstance(tf, list)
                    and required.issubset(set(tf))
                    and isinstance(td, list)
                    and ("融資融券彙總" in title or tf[0] == "代號")
                ):
                    return t

        fields = payload.get("fields")
        data = payload.get("data")
        if isinstance(fields, list) and required.issubset(set(fields)) and isinstance(data, list):
            return {"fields": fields, "data": data}

        raise SchemaValidationError("Official TWSE margin table not found", provider=provider)

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
                    and len(tf) >= 20
                    and isinstance(td, list)
                    and (t.get("title") == "上櫃股票融資融券餘額" or tf[0] in {"代號", "證券代號"})
                ):
                    return t
        raise SchemaValidationError("Official TPEx margin table not found", provider=provider)
