"""Official sampling reconciliation between TWSE/TPEx raw snapshots and normalized models."""

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel

from qmo.models.institutional import InstitutionalFlow
from qmo.models.margin import Margin
from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.validation.models import CheckSeverity, ValidationCheckResult


def _normalize_official_date(raw_date: Any) -> Optional[str]:
    """Normalize raw official date string (ISO, ROC YYY/MM/DD, YYYMMDD) to ISO YYYY-MM-DD."""
    if not raw_date:
        return None
    s = str(raw_date).strip().replace("-", "").replace("/", "").replace(".", "")
    if len(s) == 8 and s.isdigit() and s.startswith("20"):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) == 7 and s.isdigit():
        year = int(s[:3]) + 1911
        return f"{year:04d}-{s[3:5]}-{s[5:7]}"
    if len(s) == 6 and s.isdigit():
        year = int(s[:2]) + 1911
        return f"{year:04d}-{s[2:4]}-{s[4:6]}"
    if len(str(raw_date)) == 10 and str(raw_date)[4] == "-" and str(raw_date)[7] == "-":
        return str(raw_date)
    return None


def _strict_int(val_str: Any) -> int:
    s = str(val_str).strip().replace(",", "") if val_str is not None else ""
    if not s or s == "--":
        return 0
    return int(s)


def _strict_float(val_str: Any) -> Optional[float]:
    s = str(val_str).strip().replace(",", "") if val_str is not None else ""
    if not s or s == "--":
        return None
    return float(s)


class OfficialReconciler:
    """Reconciles normalized model records against official TWSE/TPEx raw response snapshots."""

    @classmethod
    def reconcile_batch(
        cls,
        dataset: str,
        models: Sequence[BaseModel],
        twse_envelope: Optional[RawResponseEnvelope] = None,
        tpex_envelope: Optional[RawResponseEnvelope] = None,
        min_match_rate_pct: float = 99.5,
    ) -> ValidationCheckResult:
        """Dispatcher to run dataset-specific official reconciliation."""
        if dataset == "daily_price":
            price_models = [m for m in models if isinstance(m, DailyPrice)]
            return cls.reconcile_daily_prices(
                price_models, twse_envelope, tpex_envelope, min_match_rate_pct
            )
        elif dataset == "institutional_flow":
            flow_models = [m for m in models if isinstance(m, InstitutionalFlow)]
            return cls.reconcile_institutional_flow(
                flow_models, twse_envelope, tpex_envelope, min_match_rate_pct
            )
        elif dataset == "margin":
            margin_models = [m for m in models if isinstance(m, Margin)]
            return cls.reconcile_margin(
                margin_models, twse_envelope, tpex_envelope, min_match_rate_pct
            )

        return ValidationCheckResult(
            check_name="official_sampling_reconciliation",
            severity=CheckSeverity.INFO,
            passed=True,
            message=f"No official reconciliation rules defined for dataset '{dataset}'",
            details={},
        )

    @classmethod
    def reconcile_daily_prices(
        cls,
        models: Sequence[DailyPrice],
        twse_envelope: Optional[RawResponseEnvelope] = None,
        tpex_envelope: Optional[RawResponseEnvelope] = None,
        min_match_rate_pct: float = 99.5,
    ) -> ValidationCheckResult:
        """Cross-check DailyPrice models against official TWSE/TPEx raw envelopes.

        Uses strict composite key (trade_date, stock_id, market). NO fallback allowed.
        """
        raw_map, parse_errors = cls._parse_raw_prices(twse_envelope, tpex_envelope)

        if parse_errors:
            err_str = "; ".join(parse_errors)
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.CRITICAL,
                passed=False,
                message=f"Official price raw envelope parsing failed: {err_str}",
                details={"errors": parse_errors},
            )

        if not raw_map:
            if twse_envelope or tpex_envelope:
                return ValidationCheckResult(
                    check_name="official_sampling_reconciliation",
                    severity=CheckSeverity.CRITICAL,
                    passed=False,
                    message="Official price raw envelopes were provided but yielded 0 raw entries",
                    details={"parse_errors": parse_errors},
                )
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.INFO,
                passed=True,
                message=(
                    "No official TWSE/TPEx price envelopes provided for reconciliation sampling"
                ),
                details={"sample_count": 0},
            )

        matched_count = 0
        mismatched_count = 0
        mismatches: List[Dict[str, Any]] = []

        for m in models:
            key = (m.trade_date, m.stock_id, m.market.upper())
            raw_info = raw_map.get(key)

            if raw_info:
                raw_close = raw_info.get("close_price")
                raw_vol = raw_info.get("trading_volume")

                price_match = (m.close_price is None and raw_close is None) or (
                    m.close_price is not None
                    and raw_close is not None
                    and abs(m.close_price - raw_close) < 1e-4
                )
                vol_match = m.trading_volume == raw_vol

                if price_match and vol_match:
                    matched_count += 1
                else:
                    mismatched_count += 1
                    mismatches.append(
                        {
                            "key": f"{m.trade_date}:{m.stock_id}:{m.market}",
                            "normalized": {
                                "close_price": m.close_price,
                                "trading_volume": m.trading_volume,
                            },
                            "raw_official": {
                                "close_price": raw_close,
                                "trading_volume": raw_vol,
                            },
                        }
                    )

        total_samples = matched_count + mismatched_count

        if total_samples == 0:
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.CRITICAL,
                passed=False,
                message=(
                    "Zero matching sample intersection between official price envelopes "
                    "and normalized models"
                ),
                details={"raw_entries": len(raw_map), "model_entries": len(models)},
            )

        match_rate_pct = round((matched_count / total_samples * 100), 2)
        passed = match_rate_pct >= min_match_rate_pct
        msg = (
            f"Official price reconciliation passed: {match_rate_pct}% match "
            f"({matched_count}/{total_samples})"
            if passed
            else (
                f"Official price reconciliation match rate {match_rate_pct}% below "
                f"threshold {min_match_rate_pct}% ({mismatched_count} mismatches)"
            )
        )

        return ValidationCheckResult(
            check_name="official_sampling_reconciliation",
            severity=CheckSeverity.CRITICAL if not passed else CheckSeverity.INFO,
            passed=passed,
            message=msg,
            details={
                "match_rate_pct": match_rate_pct,
                "matched_count": matched_count,
                "mismatched_count": mismatched_count,
                "total_samples": total_samples,
                "mismatches": mismatches[:5],
            },
        )

    @classmethod
    def reconcile_institutional_flow(
        cls,
        models: Sequence[InstitutionalFlow],
        twse_envelope: Optional[RawResponseEnvelope] = None,
        tpex_envelope: Optional[RawResponseEnvelope] = None,
        min_match_rate_pct: float = 99.5,
    ) -> ValidationCheckResult:
        """Cross-check InstitutionalFlow models against official TWSE/TPEx raw envelopes."""
        raw_map, parse_errors = cls._parse_raw_institutional(twse_envelope, tpex_envelope)

        if parse_errors:
            err_str = "; ".join(parse_errors)
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.CRITICAL,
                passed=False,
                message=f"Official institutional raw envelope parsing failed: {err_str}",
                details={"errors": parse_errors},
            )

        if not raw_map:
            if twse_envelope or tpex_envelope:
                return ValidationCheckResult(
                    check_name="official_sampling_reconciliation",
                    severity=CheckSeverity.CRITICAL,
                    passed=False,
                    message=(
                        "Official institutional raw envelopes were provided but yielded 0 entries"
                    ),
                    details={"parse_errors": parse_errors},
                )
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.INFO,
                passed=True,
                message=(
                    "No official institutional raw envelopes provided for reconciliation sampling"
                ),
                details={"sample_count": 0},
            )

        matched_count = 0
        mismatched_count = 0
        mismatches: List[Dict[str, Any]] = []

        for m in models:
            key = (m.trade_date, m.stock_id, m.market.upper())
            raw_info = raw_map.get(key)

            if raw_info:
                net_match = m.total_net == raw_info.get("total_net")
                if net_match:
                    matched_count += 1
                else:
                    mismatched_count += 1
                    mismatches.append(
                        {
                            "key": f"{m.trade_date}:{m.stock_id}:{m.market}",
                            "normalized_total_net": m.total_net,
                            "raw_official_total_net": raw_info.get("total_net"),
                        }
                    )

        total_samples = matched_count + mismatched_count
        if total_samples == 0:
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.CRITICAL,
                passed=False,
                message=(
                    "Zero matching sample intersection between official institutional "
                    "envelopes and normalized models"
                ),
                details={"raw_entries": len(raw_map), "model_entries": len(models)},
            )

        match_rate_pct = round((matched_count / total_samples * 100), 2)
        passed = match_rate_pct >= min_match_rate_pct
        msg = (
            f"Official institutional flow reconciliation passed: {match_rate_pct}% match "
            f"({matched_count}/{total_samples})"
            if passed
            else (
                f"Official institutional reconciliation match rate {match_rate_pct}% "
                "below threshold"
            )
        )

        return ValidationCheckResult(
            check_name="official_sampling_reconciliation",
            severity=CheckSeverity.CRITICAL if not passed else CheckSeverity.INFO,
            passed=passed,
            message=msg,
            details={
                "match_rate_pct": match_rate_pct,
                "matched_count": matched_count,
                "mismatched_count": mismatched_count,
                "total_samples": total_samples,
                "mismatches": mismatches[:5],
            },
        )

    @classmethod
    def reconcile_margin(
        cls,
        models: Sequence[Margin],
        twse_envelope: Optional[RawResponseEnvelope] = None,
        tpex_envelope: Optional[RawResponseEnvelope] = None,
        min_match_rate_pct: float = 99.5,
    ) -> ValidationCheckResult:
        """Cross-check normalized Margin models against official TWSE/TPEx raw envelopes."""
        raw_map, parse_errors = cls._parse_raw_margin(twse_envelope, tpex_envelope)

        if parse_errors:
            err_str = "; ".join(parse_errors)
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.CRITICAL,
                passed=False,
                message=f"Official margin raw envelope parsing failed: {err_str}",
                details={"errors": parse_errors},
            )

        if not raw_map:
            if twse_envelope or tpex_envelope:
                return ValidationCheckResult(
                    check_name="official_sampling_reconciliation",
                    severity=CheckSeverity.CRITICAL,
                    passed=False,
                    message="Official margin raw envelopes were provided but yielded 0 entries",
                    details={"parse_errors": parse_errors},
                )
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.INFO,
                passed=True,
                message="No official margin raw envelopes provided for reconciliation sampling",
                details={"sample_count": 0},
            )

        matched_count = 0
        mismatched_count = 0
        mismatches: List[Dict[str, Any]] = []

        for m in models:
            key = (m.trade_date, m.stock_id, m.market.upper())
            raw_info = raw_map.get(key)

            if raw_info:
                margin_bal_match = m.margin_purchase_balance == raw_info.get(
                    "margin_purchase_balance"
                )
                short_bal_match = m.short_sale_balance == raw_info.get("short_sale_balance")

                if margin_bal_match and short_bal_match:
                    matched_count += 1
                else:
                    mismatched_count += 1
                    mismatches.append(
                        {
                            "key": f"{m.trade_date}:{m.stock_id}:{m.market}",
                            "normalized": {
                                "margin_bal": m.margin_purchase_balance,
                                "short_bal": m.short_sale_balance,
                            },
                            "raw_official": {
                                "margin_bal": raw_info.get("margin_purchase_balance"),
                                "short_bal": raw_info.get("short_sale_balance"),
                            },
                        }
                    )

        total_samples = matched_count + mismatched_count
        if total_samples == 0:
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.CRITICAL,
                passed=False,
                message=(
                    "Zero matching sample intersection between official margin envelopes "
                    "and normalized models"
                ),
                details={"raw_entries": len(raw_map), "model_entries": len(models)},
            )

        match_rate_pct = round((matched_count / total_samples * 100), 2)
        passed = match_rate_pct >= min_match_rate_pct
        msg = (
            f"Official margin reconciliation passed: {match_rate_pct}% match "
            f"({matched_count}/{total_samples})"
            if passed
            else (f"Official margin reconciliation match rate {match_rate_pct}% below threshold")
        )

        return ValidationCheckResult(
            check_name="official_sampling_reconciliation",
            severity=CheckSeverity.CRITICAL if not passed else CheckSeverity.INFO,
            passed=passed,
            message=msg,
            details={
                "match_rate_pct": match_rate_pct,
                "matched_count": matched_count,
                "mismatched_count": mismatched_count,
                "total_samples": total_samples,
                "mismatches": mismatches[:5],
            },
        )

    @classmethod
    def _parse_raw_prices(
        cls,
        twse_env: Optional[RawResponseEnvelope],
        tpex_env: Optional[RawResponseEnvelope],
    ) -> Tuple[Dict[Any, Dict[str, Any]], List[str]]:
        raw_map: Dict[Any, Dict[str, Any]] = {}
        errors: List[str] = []

        if twse_env and twse_env.raw_body_bytes:
            if twse_env.status_code != 200:
                errors.append(
                    f"TWSE price envelope returned HTTP status {twse_env.status_code}, expected 200"
                )
            else:
                try:
                    twse_json = json.loads(twse_env.raw_body_bytes.decode("utf-8"))
                    data_list = twse_json.get("data", [])
                    fields = twse_json.get("fields", [])
                    raw_date = twse_json.get("date") or (
                        twse_env.params.get("date") if twse_env.params else None
                    )
                    norm_date = _normalize_official_date(raw_date)

                    if not norm_date:
                        errors.append("TWSE price payload missing valid official date")
                    elif not data_list or not fields:
                        errors.append("TWSE price payload missing 'data' or 'fields'")
                    elif (
                        "證券代號" not in fields
                        or "收盤價" not in fields
                        or "成交股數" not in fields
                    ):
                        errors.append(
                            "TWSE price payload missing required fields "
                            "('證券代號', '收盤價', '成交股數')"
                        )
                    else:
                        stock_idx = fields.index("證券代號")
                        close_idx = fields.index("收盤價")
                        vol_idx = fields.index("成交股數")

                        for row in data_list:
                            if len(row) > max(stock_idx, close_idx, vol_idx):
                                sid = str(row[stock_idx]).strip()
                                close_val = _strict_float(row[close_idx])
                                vol_val = _strict_int(row[vol_idx])

                                entry = {
                                    "close_price": close_val,
                                    "trading_volume": vol_val,
                                    "market": "TWSE",
                                }
                                raw_map[(norm_date, sid, "TWSE")] = entry
                except Exception as e:
                    errors.append(f"TWSE price payload parsing error: {e}")

        if tpex_env and tpex_env.raw_body_bytes:
            if tpex_env.status_code != 200:
                errors.append(
                    f"TPEx price envelope returned HTTP status {tpex_env.status_code}, expected 200"
                )
            else:
                try:
                    tpex_json = json.loads(tpex_env.raw_body_bytes.decode("utf-8"))
                    tables = tpex_json.get("aaData", []) or tpex_json.get("tables", [])
                    raw_date = (
                        tpex_json.get("reportDate")
                        or tpex_json.get("date")
                        or (tpex_env.params.get("date") if tpex_env.params else None)
                    )
                    norm_date = _normalize_official_date(raw_date)

                    if not norm_date:
                        errors.append("TPEx price payload missing valid official date")
                    elif not tables:
                        errors.append("TPEx price payload missing 'aaData' or 'tables'")
                    else:
                        for row in tables:
                            if isinstance(row, list) and len(row) >= 9:
                                sid = str(row[0]).strip()
                                close_val = _strict_float(row[2])
                                vol_val = _strict_int(row[8])

                                entry = {
                                    "close_price": close_val,
                                    "trading_volume": vol_val,
                                    "market": "TPEX",
                                }
                                raw_map[(norm_date, sid, "TPEX")] = entry
                except Exception as e:
                    errors.append(f"TPEx price payload parsing error: {e}")

        return raw_map, errors

    @classmethod
    def _parse_raw_institutional(
        cls,
        twse_env: Optional[RawResponseEnvelope],
        tpex_env: Optional[RawResponseEnvelope],
    ) -> Tuple[Dict[Any, Dict[str, Any]], List[str]]:
        raw_map: Dict[Any, Dict[str, Any]] = {}
        errors: List[str] = []

        if twse_env and twse_env.raw_body_bytes:
            if twse_env.status_code != 200:
                errors.append(
                    f"TWSE institutional envelope status is {twse_env.status_code}, expected 200"
                )
            else:
                try:
                    twse_json = json.loads(twse_env.raw_body_bytes.decode("utf-8"))
                    data_list = twse_json.get("data", [])
                    fields = twse_json.get("fields", [])
                    raw_date = twse_json.get("date") or (
                        twse_env.params.get("date") if twse_env.params else None
                    )
                    norm_date = _normalize_official_date(raw_date)

                    if not norm_date:
                        errors.append("TWSE institutional payload missing valid official date")
                    elif not data_list or not fields:
                        errors.append("TWSE institutional payload missing 'data' or 'fields'")
                    else:
                        stock_idx = (
                            fields.index("證券代號")
                            if "證券代號" in fields
                            else (fields.index("股票代號") if "股票代號" in fields else -1)
                        )
                        net_idx = -1
                        for name in (
                            "三大法人買賣超股數",
                            "三大法人買賣超金額",
                            "買賣超股數",
                            "三大法人買賣超",
                        ):
                            if name in fields:
                                net_idx = fields.index(name)
                                break

                        if stock_idx == -1 or net_idx == -1:
                            errors.append("TWSE institutional payload missing '三大法人買賣超股數'")
                        else:
                            for row in data_list:
                                if len(row) > max(stock_idx, net_idx):
                                    sid = str(row[stock_idx]).strip()
                                    net_val = _strict_int(row[net_idx])

                                    entry = {"total_net": net_val, "market": "TWSE"}
                                    raw_map[(norm_date, sid, "TWSE")] = entry
                except Exception as e:
                    errors.append(f"TWSE institutional payload parsing error: {e}")

        if tpex_env and tpex_env.raw_body_bytes:
            if tpex_env.status_code != 200:
                errors.append(
                    f"TPEx institutional envelope status is {tpex_env.status_code}, expected 200"
                )
            else:
                try:
                    tpex_json = json.loads(tpex_env.raw_body_bytes.decode("utf-8"))
                    tables = tpex_json.get("aaData", []) or tpex_json.get("tables", [])
                    fields = tpex_json.get("fields", [])
                    raw_date = (
                        tpex_json.get("reportDate")
                        or tpex_json.get("date")
                        or (tpex_env.params.get("date") if tpex_env.params else None)
                    )
                    norm_date = _normalize_official_date(raw_date)

                    if not norm_date:
                        errors.append("TPEx institutional payload missing valid official date")
                    elif not tables:
                        errors.append("TPEx institutional payload missing tables")
                    else:
                        stock_idx = 0
                        net_idx = -1
                        if fields:
                            if "代號" in fields:
                                stock_idx = fields.index("代號")
                            elif "證券代號" in fields:
                                stock_idx = fields.index("證券代號")

                            for name in (
                                "三大法人買賣超股數",
                                "三大法人買賣超合計",
                                "買賣超股數",
                            ):
                                if name in fields:
                                    net_idx = fields.index(name)
                                    break
                        else:
                            net_idx = 9 if len(tables[0]) > 9 else -1

                        if net_idx == -1:
                            errors.append("TPEx institutional payload missing '三大法人買賣超股數'")
                        else:
                            for row in tables:
                                if isinstance(row, list) and len(row) > max(stock_idx, net_idx):
                                    sid = str(row[stock_idx]).strip()
                                    net_val = _strict_int(row[net_idx])
                                    entry = {"total_net": net_val, "market": "TPEX"}
                                    raw_map[(norm_date, sid, "TPEX")] = entry
                except Exception as e:
                    errors.append(f"TPEx institutional payload parsing error: {e}")

        return raw_map, errors

    @classmethod
    def _parse_raw_margin(
        cls,
        twse_env: Optional[RawResponseEnvelope],
        tpex_env: Optional[RawResponseEnvelope],
    ) -> Tuple[Dict[Any, Dict[str, Any]], List[str]]:
        raw_map: Dict[Any, Dict[str, Any]] = {}
        errors: List[str] = []

        if twse_env and twse_env.raw_body_bytes:
            if twse_env.status_code != 200:
                errors.append(f"TWSE margin envelope returned HTTP status {twse_env.status_code}")
            else:
                try:
                    twse_json = json.loads(twse_env.raw_body_bytes.decode("utf-8"))
                    data_list = twse_json.get("data", [])
                    fields = twse_json.get("fields", [])
                    raw_date = twse_json.get("date") or (
                        twse_env.params.get("date") if twse_env.params else None
                    )
                    norm_date = _normalize_official_date(raw_date)

                    if not norm_date:
                        errors.append("TWSE margin payload missing valid official date")
                    elif not data_list or not fields:
                        errors.append("TWSE margin payload missing 'data' or 'fields'")
                    else:
                        stock_idx = (
                            fields.index("股票代號")
                            if "股票代號" in fields
                            else (fields.index("證券代號") if "證券代號" in fields else -1)
                        )
                        mb_idx = -1
                        for name in (
                            "融資今日餘額",
                            "融資金額今日餘額",
                            "融資餘額",
                            "融資(張)今日餘額",
                            "今日餘額",
                        ):
                            if name in fields:
                                mb_idx = fields.index(name)
                                break

                        sb_idx = -1
                        for name in (
                            "融券今日餘額",
                            "融券金額今日餘額",
                            "融券餘額",
                            "融券(張)今日餘額",
                        ):
                            if name in fields:
                                sb_idx = fields.index(name)
                                break

                        if stock_idx == -1 or mb_idx == -1 or sb_idx == -1:
                            errors.append(
                                "TWSE margin payload missing required balance fields "
                                "('融資今日餘額', '融券今日餘額')"
                            )
                        else:
                            for row in data_list:
                                if len(row) > max(stock_idx, mb_idx, sb_idx):
                                    sid = str(row[stock_idx]).strip()
                                    margin_bal = _strict_int(row[mb_idx])
                                    short_bal = _strict_int(row[sb_idx])

                                    raw_map[(norm_date, sid, "TWSE")] = {
                                        "margin_purchase_balance": margin_bal,
                                        "short_sale_balance": short_bal,
                                        "market": "TWSE",
                                    }
                except Exception as e:
                    errors.append(f"TWSE margin payload parsing error: {e}")

        if tpex_env and tpex_env.raw_body_bytes:
            if tpex_env.status_code != 200:
                errors.append(f"TPEx margin envelope returned HTTP status {tpex_env.status_code}")
            else:
                try:
                    tpex_json = json.loads(tpex_env.raw_body_bytes.decode("utf-8"))
                    tables = tpex_json.get("aaData", []) or tpex_json.get("tables", [])
                    fields = tpex_json.get("fields", [])
                    raw_date = (
                        tpex_json.get("reportDate")
                        or tpex_json.get("date")
                        or (tpex_env.params.get("date") if tpex_env.params else None)
                    )
                    norm_date = _normalize_official_date(raw_date)

                    if not norm_date:
                        errors.append("TPEx margin payload missing valid official date")
                    elif not tables:
                        errors.append("TPEx margin payload missing tables")
                    else:
                        stock_idx = 0
                        mb_idx = -1
                        sb_idx = -1
                        if fields:
                            if "代號" in fields:
                                stock_idx = fields.index("代號")
                            elif "證券代號" in fields:
                                stock_idx = fields.index("證券代號")

                            for name in (
                                "融資今日餘額",
                                "融資金額今日餘額",
                                "融資餘額",
                                "今日餘額",
                            ):
                                if name in fields:
                                    mb_idx = fields.index(name)
                                    break
                            for name in ("融券今日餘額", "融券金額今日餘額", "融券餘額"):
                                if name in fields:
                                    sb_idx = fields.index(name)
                                    break
                        else:
                            mb_idx = 6 if len(tables[0]) > 6 else -1
                            sb_idx = 12 if len(tables[0]) > 12 else -1

                        if mb_idx == -1 or sb_idx == -1:
                            errors.append(
                                "TPEx margin payload missing required fields "
                                "('融資今日餘額', '融券今日餘額')"
                            )
                        else:
                            for row in tables:
                                if isinstance(row, list) and len(row) > max(
                                    stock_idx, mb_idx, sb_idx
                                ):
                                    sid = str(row[stock_idx]).strip()
                                    margin_bal = _strict_int(row[mb_idx])
                                    short_bal = _strict_int(row[sb_idx])

                                    raw_map[(norm_date, sid, "TPEX")] = {
                                        "margin_purchase_balance": margin_bal,
                                        "short_sale_balance": short_bal,
                                        "market": "TPEX",
                                    }
                except Exception as e:
                    errors.append(f"TPEx margin payload parsing error: {e}")

        return raw_map, errors
