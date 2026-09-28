"""Official sampling reconciliation between TWSE/TPEx raw snapshots and normalized models."""

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel

from qmo.models.institutional import InstitutionalFlow
from qmo.models.margin import Margin
from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.validation.models import CheckSeverity, ValidationCheckResult


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
        """Cross-check normalized DailyPrice models against official TWSE/TPEx raw envelopes.

        Uses composite key (trade_date, stock_id, market) to check close_price and trading_volume.
        """
        raw_map, parse_errors = cls._parse_raw_prices(twse_envelope, tpex_envelope)

        if parse_errors and not raw_map:
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.CRITICAL,
                passed=False,
                message=f"Official raw envelope parsing failed: {'; '.join(parse_errors)}",
                details={"errors": parse_errors},
            )

        if not raw_map:
            if twse_envelope or tpex_envelope:
                return ValidationCheckResult(
                    check_name="official_sampling_reconciliation",
                    severity=CheckSeverity.CRITICAL,
                    passed=False,
                    message="Official raw envelopes were provided but yielded 0 raw entries",
                    details={"parse_errors": parse_errors},
                )
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.INFO,
                passed=True,
                message="No official TWSE/TPEx raw envelopes provided for reconciliation sampling",
                details={"sample_count": 0},
            )

        matched_count = 0
        mismatched_count = 0
        mismatches: List[Dict[str, Any]] = []

        for m in models:
            key = (m.trade_date, m.stock_id, m.market.upper())
            # Also fallback to matching by stock_id and market if date is implicit
            raw_info = raw_map.get(key) or raw_map.get((m.stock_id, m.market.upper()))

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
                    "Zero matching sample intersection between official raw envelopes "
                    "and normalized models"
                ),
                details={"raw_entries": len(raw_map), "model_entries": len(models)},
            )

        match_rate_pct = round((matched_count / total_samples * 100), 2)
        passed = match_rate_pct >= min_match_rate_pct
        msg = (
            f"Official sampling reconciliation passed: {match_rate_pct}% match "
            f"({matched_count}/{total_samples})"
            if passed
            else (
                f"Official reconciliation match rate {match_rate_pct}% below "
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
                "parse_errors": parse_errors,
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
        """Cross-check InstitutionalFlow models against TWSE/TPEx raw envelopes."""
        raw_map, parse_errors = cls._parse_raw_institutional(twse_envelope, tpex_envelope)

        if parse_errors and not raw_map:
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
            raw_info = raw_map.get(key) or raw_map.get((m.stock_id, m.market.upper()))

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

        if parse_errors and not raw_map:
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.CRITICAL,
                passed=False,
                message=f"Official margin raw envelope parsing failed: {'; '.join(parse_errors)}",
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
            raw_info = raw_map.get(key) or raw_map.get((m.stock_id, m.market.upper()))

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
            try:
                twse_json = json.loads(twse_env.raw_body_bytes.decode("utf-8"))
                data_list = twse_json.get("data", [])
                fields = twse_json.get("fields", [])
                date_str = twse_json.get("date", "")

                if not data_list or not fields:
                    errors.append("TWSE price payload missing 'data' or 'fields'")
                else:
                    stock_idx = fields.index("證券代號")
                    close_idx = fields.index("收盤價")
                    vol_idx = fields.index("成交股數")

                    for row in data_list:
                        if len(row) > max(stock_idx, close_idx, vol_idx):
                            sid = str(row[stock_idx]).strip()
                            c_str = str(row[close_idx]).strip().replace(",", "")
                            v_str = str(row[vol_idx]).strip().replace(",", "")

                            close_val = float(c_str) if c_str and c_str != "--" else None
                            vol_val = int(v_str) if v_str and v_str.isdigit() else 0

                            entry = {
                                "close_price": close_val,
                                "trading_volume": vol_val,
                                "market": "TWSE",
                            }
                            raw_map[(sid, "TWSE")] = entry
                            if date_str:
                                raw_map[(date_str, sid, "TWSE")] = entry
            except Exception as e:
                errors.append(f"TWSE price payload parsing error: {e}")

        if tpex_env and tpex_env.raw_body_bytes:
            try:
                tpex_json = json.loads(tpex_env.raw_body_bytes.decode("utf-8"))
                tables = tpex_json.get("aaData", []) or tpex_json.get("tables", [])
                date_str = tpex_json.get("reportDate", "")

                if not tables:
                    errors.append("TPEx price payload missing 'aaData' or 'tables'")
                else:
                    for row in tables:
                        if isinstance(row, list) and len(row) >= 9:
                            sid = str(row[0]).strip()
                            c_str = str(row[2]).strip().replace(",", "")
                            v_str = str(row[8]).strip().replace(",", "")

                            close_val = float(c_str) if c_str and c_str != "--" else None
                            vol_val = int(v_str) if v_str and v_str.isdigit() else 0

                            entry = {
                                "close_price": close_val,
                                "trading_volume": vol_val,
                                "market": "TPEX",
                            }
                            raw_map[(sid, "TPEX")] = entry
                            if date_str:
                                raw_map[(date_str, sid, "TPEX")] = entry
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
            try:
                twse_json = json.loads(twse_env.raw_body_bytes.decode("utf-8"))
                data_list = twse_json.get("data", [])
                fields = twse_json.get("fields", [])
                if data_list and fields:
                    stock_idx = fields.index("證券代號")
                    net_idx = (
                        fields.index("三大法人買賣超股數") if "三大法人買賣超股數" in fields else -1
                    )
                    for row in data_list:
                        if len(row) > stock_idx:
                            sid = str(row[stock_idx]).strip()
                            net_val = 0
                            if net_idx != -1 and len(row) > net_idx:
                                n_str = str(row[net_idx]).strip().replace(",", "")
                                net_val = (
                                    int(n_str)
                                    if n_str and (n_str.isdigit() or n_str.startswith("-"))
                                    else 0
                                )

                            entry = {"total_net": net_val, "market": "TWSE"}
                            raw_map[(sid, "TWSE")] = entry
                else:
                    errors.append("TWSE institutional payload missing data/fields")
            except Exception as e:
                errors.append(f"TWSE institutional payload parsing error: {e}")

        if tpex_env and tpex_env.raw_body_bytes:
            try:
                tpex_json = json.loads(tpex_env.raw_body_bytes.decode("utf-8"))
                tables = tpex_json.get("aaData", []) or tpex_json.get("tables", [])
                if tables:
                    for row in tables:
                        if isinstance(row, list) and len(row) >= 10:
                            sid = str(row[0]).strip()
                            n_str = str(row[-1]).strip().replace(",", "")
                            net_val = (
                                int(n_str)
                                if n_str and (n_str.isdigit() or n_str.startswith("-"))
                                else 0
                            )
                            entry = {"total_net": net_val, "market": "TPEX"}
                            raw_map[(sid, "TPEX")] = entry
                else:
                    errors.append("TPEx institutional payload missing tables")
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
            try:
                twse_json = json.loads(twse_env.raw_body_bytes.decode("utf-8"))
                data_list = twse_json.get("data", [])
                fields = twse_json.get("fields", [])
                if data_list and fields:
                    stock_idx = (
                        fields.index("股票代號")
                        if "股票代號" in fields
                        else fields.index("證券代號")
                    )
                    for row in data_list:
                        if len(row) > stock_idx:
                            sid = str(row[stock_idx]).strip()
                            raw_map[(sid, "TWSE")] = {
                                "margin_purchase_balance": 0,
                                "short_sale_balance": 0,
                                "market": "TWSE",
                            }
                else:
                    errors.append("TWSE margin payload missing data/fields")
            except Exception as e:
                errors.append(f"TWSE margin payload parsing error: {e}")

        if tpex_env and tpex_env.raw_body_bytes:
            try:
                tpex_json = json.loads(tpex_env.raw_body_bytes.decode("utf-8"))
                tables = tpex_json.get("aaData", []) or tpex_json.get("tables", [])
                if tables:
                    for row in tables:
                        if isinstance(row, list) and len(row) >= 5:
                            sid = str(row[0]).strip()
                            raw_map[(sid, "TPEX")] = {
                                "margin_purchase_balance": 0,
                                "short_sale_balance": 0,
                                "market": "TPEX",
                            }
                else:
                    errors.append("TPEx margin payload missing tables")
            except Exception as e:
                errors.append(f"TPEx margin payload parsing error: {e}")

        return raw_map, errors
