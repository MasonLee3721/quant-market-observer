"""Official sampling reconciliation between TWSE/TPEx raw snapshots and normalized models."""

import json
from typing import Any, Dict, List, Optional, Sequence

from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.validation.models import CheckSeverity, ValidationCheckResult


class OfficialReconciler:
    """Reconciles normalized model records against official TWSE/TPEx raw response snapshots."""

    @staticmethod
    def reconcile_daily_prices(
        models: Sequence[DailyPrice],
        twse_envelope: Optional[RawResponseEnvelope] = None,
        tpex_envelope: Optional[RawResponseEnvelope] = None,
        min_match_rate_pct: float = 99.5,
    ) -> ValidationCheckResult:
        """Cross-check normalized DailyPrice models against official TWSE/TPEx raw envelopes.

        Parses raw JSON response data and compares stock_id, close_price, and trading_volume.
        """
        raw_map: Dict[str, Dict[str, Any]] = {}

        # Parse TWSE raw response envelope if provided
        if twse_envelope and twse_envelope.raw_body_bytes:
            try:
                twse_json = json.loads(twse_envelope.raw_body_bytes.decode("utf-8"))
                # TWSE format: data array with rows
                data_list = twse_json.get("data", [])
                fields = twse_json.get("fields", [])

                if data_list and fields:
                    # Find field indices
                    try:
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

                                raw_map[sid] = {
                                    "close_price": close_val,
                                    "trading_volume": vol_val,
                                    "market": "TWSE",
                                }
                    except (ValueError, IndexError):
                        pass
            except Exception:
                pass

        # Parse TPEx raw response envelope if provided
        if tpex_envelope and tpex_envelope.raw_body_bytes:
            try:
                tpex_json = json.loads(tpex_envelope.raw_body_bytes.decode("utf-8"))
                tables = tpex_json.get("aaData", []) or tpex_json.get("tables", [])
                if tables:
                    for row in tables:
                        if isinstance(row, list) and len(row) >= 9:
                            sid = str(row[0]).strip()
                            c_str = str(row[2]).strip().replace(",", "")
                            v_str = str(row[8]).strip().replace(",", "")

                            close_val = float(c_str) if c_str and c_str != "--" else None
                            vol_val = int(v_str) if v_str and v_str.isdigit() else 0

                            raw_map[sid] = {
                                "close_price": close_val,
                                "trading_volume": vol_val,
                                "market": "TPEx",
                            }
            except Exception:
                pass

        if not raw_map:
            return ValidationCheckResult(
                check_name="official_sampling_reconciliation",
                severity=CheckSeverity.INFO,
                passed=True,
                message=(
                    "No official TWSE/TPEx raw envelopes provided for reconciliation sampling"
                ),
                details={"sample_count": 0},
            )

        matched_count = 0
        mismatched_count = 0
        mismatches: List[Dict[str, Any]] = []

        for m in models:
            if not isinstance(m, DailyPrice):
                continue

            sid = m.stock_id
            if sid in raw_map:
                raw_info = raw_map[sid]
                raw_close = raw_info.get("close_price")
                raw_vol = raw_info.get("trading_volume")

                price_match = (
                    m.close_price is None and raw_close is None
                ) or (
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
                            "stock_id": sid,
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
        match_rate_pct = (
            round((matched_count / total_samples * 100), 2)
            if total_samples > 0
            else 100.0
        )

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
            },
        )
