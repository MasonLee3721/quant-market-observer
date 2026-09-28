"""Batch Data Validator for normalized market data models."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Type

from pydantic import BaseModel

from qmo.models.institutional import InstitutionalFlow
from qmo.models.margin import Margin
from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.validation.models import (
    CheckSeverity,
    QualityGateError,
    QualityReport,
    ValidationCheckResult,
)
from qmo.validation.reconciler import OfficialReconciler

DATASET_MODEL_MAP: Dict[str, Type[BaseModel]] = {
    "daily_price": DailyPrice,
    "institutional_flow": InstitutionalFlow,
    "margin": Margin,
}


class BatchValidator:
    """Validates normalized model batches for primary key uniqueness, schema consistency,
    domain value boundaries, stock ticker coverage, dataset-model binding, and date freshness.
    """

    def __init__(
        self,
        target_tickers: Optional[Sequence[str]] = None,
        strict_coverage: bool = False,
        allow_empty_batch: bool = False,
        max_stale_days: Optional[int] = None,
    ) -> None:
        self.target_tickers = target_tickers
        self.strict_coverage = strict_coverage
        self.allow_empty_batch = allow_empty_batch
        self.max_stale_days = max_stale_days

    def validate_batch(
        self,
        batch_id: str,
        dataset: str,
        models: Sequence[BaseModel],
        schema_version: str = "schema-v0.1",
        target_tickers: Optional[Sequence[str]] = None,
        expected_date_range: Optional[str] = None,
        twse_envelope: Optional[RawResponseEnvelope] = None,
        tpex_envelope: Optional[RawResponseEnvelope] = None,
        raise_on_failure: bool = True,
    ) -> QualityReport:
        """Run all validation checks on a batch of models and generate QualityReport."""
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()
        results: List[ValidationCheckResult] = []

        # 1. Non-empty check
        non_empty_result = self._check_non_empty(models)
        results.append(non_empty_result)

        if not models:
            overall_passed = non_empty_result.passed
            report = QualityReport(
                batch_id=batch_id,
                dataset=dataset,
                created_at=now_iso,
                overall_passed=overall_passed,
                check_results=results,
                summary={
                    "total_records": 0,
                    "unique_stocks": 0,
                    "date_range": "N/A",
                    "total_checks": len(results),
                    "passed_checks": sum(1 for r in results if r.passed),
                },
            )
            if raise_on_failure and not overall_passed:
                raise QualityGateError(report)
            return report

        # 2. Dataset <-> Model Class binding contract check
        results.append(self._check_dataset_model_binding(models, dataset))

        # 3. Schema version consistency check
        results.append(self._check_schema_version(models, schema_version))

        # 4. Primary key uniqueness check
        results.append(self._check_primary_key_uniqueness(models))

        # 5. Domain boundaries check (prices, volume, flow balance)
        results.append(self._check_domain_boundaries(models))

        # 6. Target ticker coverage check
        active_tickers = target_tickers or self.target_tickers
        if active_tickers is not None:
            results.append(self._check_ticker_coverage(models, active_tickers))

        # 7. Date freshness, future date, and range validity check
        date_check_result, min_date, max_date = self._check_dates_and_freshness(
            models, now_utc=now_utc, expected_date_range=expected_date_range
        )
        results.append(date_check_result)

        # 8. Official Reconciliation check (if raw envelopes supplied or dataset supports it)
        if twse_envelope is not None or tpex_envelope is not None:
            reconcile_result = OfficialReconciler.reconcile_batch(
                dataset=dataset,
                models=models,
                twse_envelope=twse_envelope,
                tpex_envelope=tpex_envelope,
            )
            results.append(reconcile_result)

        # Determine overall quality gate pass/fail
        overall_passed = all(r.passed for r in results if r.severity == CheckSeverity.CRITICAL)

        unique_stocks = len({getattr(m, "stock_id", "") for m in models if hasattr(m, "stock_id")})
        date_range_str = f"{min_date} to {max_date}" if min_date and max_date else "N/A"

        report = QualityReport(
            batch_id=batch_id,
            dataset=dataset,
            created_at=now_iso,
            overall_passed=overall_passed,
            check_results=results,
            summary={
                "total_records": len(models),
                "unique_stocks": unique_stocks,
                "date_range": date_range_str,
                "total_checks": len(results),
                "passed_checks": sum(1 for r in results if r.passed),
            },
        )

        if raise_on_failure and not overall_passed:
            raise QualityGateError(report)

        return report

    def _check_non_empty(self, models: Sequence[BaseModel]) -> ValidationCheckResult:
        if not models:
            passed = self.allow_empty_batch
            return ValidationCheckResult(
                check_name="non_empty_batch",
                severity=CheckSeverity.CRITICAL,
                passed=passed,
                message=(
                    "Batch is empty (0 records)" if not passed else "Batch is empty (allowed)"
                ),
                details={"record_count": 0},
            )
        return ValidationCheckResult(
            check_name="non_empty_batch",
            severity=CheckSeverity.CRITICAL,
            passed=True,
            message=f"Batch contains {len(models)} record(s)",
            details={"record_count": len(models)},
        )

    def _check_dataset_model_binding(
        self, models: Sequence[BaseModel], dataset: str
    ) -> ValidationCheckResult:
        expected_cls = DATASET_MODEL_MAP.get(dataset)
        if expected_cls is None:
            return ValidationCheckResult(
                check_name="dataset_model_binding",
                severity=CheckSeverity.WARNING,
                passed=True,
                message=f"No dataset-model binding rule registered for dataset '{dataset}'",
                details={},
            )

        mismatches: List[str] = []
        for idx, m in enumerate(models):
            if not isinstance(m, expected_cls):
                mismatches.append(
                    f"Row {idx}: expected {expected_cls.__name__}, got {type(m).__name__}"
                )

        passed = len(mismatches) == 0
        msg = (
            f"All {len(models)} record(s) conform to contract '{expected_cls.__name__}'"
            if passed
            else f"Dataset-model binding violation: {len(mismatches)} invalid model instance(s)"
        )

        return ValidationCheckResult(
            check_name="dataset_model_binding",
            severity=CheckSeverity.CRITICAL,
            passed=passed,
            message=msg,
            details={"mismatch_count": len(mismatches), "mismatches": mismatches[:5]},
        )

    def _check_schema_version(
        self, models: Sequence[BaseModel], expected_version: str
    ) -> ValidationCheckResult:
        mismatches: List[Dict[str, Any]] = []
        for idx, m in enumerate(models):
            ver = getattr(m, "schema_version", None)
            if ver != expected_version:
                mismatches.append({"index": idx, "expected": expected_version, "actual": ver})

        passed = len(mismatches) == 0
        msg = (
            "All records match schema version contract"
            if passed
            else f"Schema version mismatch found in {len(mismatches)} record(s)"
        )
        return ValidationCheckResult(
            check_name="schema_version_consistency",
            severity=CheckSeverity.CRITICAL,
            passed=passed,
            message=msg,
            details={"mismatch_count": len(mismatches), "mismatches": mismatches[:5]},
        )

    def _check_primary_key_uniqueness(self, models: Sequence[BaseModel]) -> ValidationCheckResult:
        seen_keys: Set[tuple[Any, ...]] = set()
        duplicate_keys: List[tuple[Any, ...]] = []

        for m in models:
            date_val = getattr(m, "trade_date", None)
            stock_val = getattr(m, "stock_id", None)
            key = (date_val, stock_val)

            if key in seen_keys:
                duplicate_keys.append(key)
            else:
                seen_keys.add(key)

        passed = len(duplicate_keys) == 0
        msg = (
            "Composite primary key (trade_date, stock_id) is unique across all records"
            if passed
            else f"Duplicate primary key(s) detected: {len(duplicate_keys)} duplicate(s)"
        )
        return ValidationCheckResult(
            check_name="primary_key_uniqueness",
            severity=CheckSeverity.CRITICAL,
            passed=passed,
            message=msg,
            details={
                "duplicate_count": len(duplicate_keys),
                "duplicates": duplicate_keys[:5],
            },
        )

    def _check_domain_boundaries(self, models: Sequence[BaseModel]) -> ValidationCheckResult:
        violations: List[str] = []

        for idx, m in enumerate(models):
            if isinstance(m, DailyPrice):
                # Price boundaries
                if m.open_price is not None and m.open_price <= 0:
                    violations.append(f"Row {idx} ({m.stock_id}): open_price <= 0 ({m.open_price})")
                if m.close_price is not None and m.close_price <= 0:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): close_price <= 0 ({m.close_price})"
                    )
                if m.high_price is not None and m.low_price is not None:
                    if m.high_price < m.low_price:
                        violations.append(
                            f"Row {idx} ({m.stock_id}): high_price ({m.high_price}) "
                            f"< low_price ({m.low_price})"
                        )

                # Volume & Value boundaries
                if m.trading_volume < 0:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): trading_volume < 0 ({m.trading_volume})"
                    )
                if m.trading_value < 0:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): trading_value < 0 ({m.trading_value})"
                    )

                # No trade contract semantics
                if m.trading_volume == 0 and m.trading_value == 0:
                    if not m.no_trade:
                        violations.append(
                            f"Row {idx} ({m.stock_id}): volume & value are 0 but no_trade is False"
                        )
                    if m.open_price is not None or m.close_price is not None:
                        violations.append(
                            f"Row {idx} ({m.stock_id}): no_trade is True but prices are not None"
                        )

            elif isinstance(m, InstitutionalFlow):
                # Verify net calculations
                expected_foreign_net = m.foreign_buy - m.foreign_sell
                if m.foreign_net != expected_foreign_net:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): foreign_net {m.foreign_net} "
                        f"!= buy-sell {expected_foreign_net}"
                    )

                expected_it_net = m.investment_trust_buy - m.investment_trust_sell
                if m.investment_trust_net != expected_it_net:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): investment_trust_net "
                        f"{m.investment_trust_net} != buy-sell {expected_it_net}"
                    )

                expected_dealer_net = m.dealer_buy - m.dealer_sell
                if m.dealer_net != expected_dealer_net:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): dealer_net {m.dealer_net} "
                        f"!= buy-sell {expected_dealer_net}"
                    )

                expected_total_net = m.foreign_net + m.investment_trust_net + m.dealer_net
                if m.total_net != expected_total_net:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): total_net {m.total_net} "
                        f"!= sum of nets {expected_total_net}"
                    )

            elif isinstance(m, Margin):
                if m.margin_purchase_balance < 0:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): margin_purchase_balance < 0 "
                        f"({m.margin_purchase_balance})"
                    )
                if m.short_sale_balance < 0:
                    violations.append(
                        f"Row {idx} ({m.stock_id}): short_sale_balance < 0 ({m.short_sale_balance})"
                    )
                if (
                    m.margin_purchase_quota > 0
                    and m.margin_purchase_balance > m.margin_purchase_quota
                ):
                    violations.append(
                        f"Row {idx} ({m.stock_id}): margin_purchase_balance "
                        f"({m.margin_purchase_balance}) > quota ({m.margin_purchase_quota})"
                    )

        passed = len(violations) == 0
        msg = (
            "Domain value boundaries and semantic rules satisfied"
            if passed
            else f"Domain boundary violations detected: {len(violations)} issue(s)"
        )
        return ValidationCheckResult(
            check_name="domain_boundaries",
            severity=CheckSeverity.CRITICAL,
            passed=passed,
            message=msg,
            details={"violation_count": len(violations), "violations": violations[:5]},
        )

    def _check_ticker_coverage(
        self, models: Sequence[BaseModel], target_tickers: Sequence[str]
    ) -> ValidationCheckResult:
        present_tickers = {getattr(m, "stock_id", "") for m in models if hasattr(m, "stock_id")}
        target_set = set(target_tickers)
        missing_tickers = sorted(target_set - present_tickers)

        passed = len(missing_tickers) == 0
        severity = CheckSeverity.CRITICAL if self.strict_coverage else CheckSeverity.WARNING

        coverage_pct = (
            round((len(target_set - set(missing_tickers)) / len(target_set)) * 100, 2)
            if target_set
            else 100.0
        )

        msg = (
            f"Stock ticker coverage is 100% ({len(present_tickers)} / {len(target_set)})"
            if passed
            else (
                f"Missing {len(missing_tickers)} ticker(s) from target pool "
                f"(Coverage: {coverage_pct}%)"
            )
        )

        return ValidationCheckResult(
            check_name="stock_ticker_coverage",
            severity=severity,
            passed=passed,
            message=msg,
            details={
                "coverage_pct": coverage_pct,
                "target_count": len(target_set),
                "present_count": len(present_tickers),
                "missing_tickers": missing_tickers[:10],
            },
        )

    def _check_dates_and_freshness(
        self,
        models: Sequence[BaseModel],
        now_utc: datetime,
        expected_date_range: Optional[str] = None,
    ) -> tuple[ValidationCheckResult, Optional[str], Optional[str]]:
        invalid_dates: List[str] = []
        dates: List[str] = []
        today_iso = now_utc.strftime("%Y-%m-%d")

        for idx, m in enumerate(models):
            d = getattr(m, "trade_date", None)
            if not d:
                invalid_dates.append(f"Row {idx}: missing trade_date")
                continue
            try:
                datetime.strptime(d, "%Y-%m-%d")
                if d > today_iso:
                    invalid_dates.append(f"Row {idx}: future date '{d}' > today '{today_iso}'")
                else:
                    dates.append(d)
            except ValueError:
                invalid_dates.append(f"Row {idx}: invalid date format '{d}'")

        if not dates:
            return (
                ValidationCheckResult(
                    check_name="date_validity_and_freshness",
                    severity=CheckSeverity.CRITICAL,
                    passed=False,
                    message="No valid trade_date found in records or future dates detected",
                    details={
                        "invalid_count": len(invalid_dates),
                        "invalid_dates": invalid_dates[:5],
                    },
                ),
                None,
                None,
            )

        min_date = min(dates)
        max_date = max(dates)

        freshness_issues: List[str] = []
        if self.max_stale_days is not None:
            max_dt = datetime.strptime(max_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            stale_days = (now_utc - max_dt).days
            if stale_days > self.max_stale_days:
                freshness_issues.append(
                    f"Max date '{max_date}' is stale by {stale_days} days "
                    f"(max allowed: {self.max_stale_days})"
                )

        if expected_date_range:
            if min_date not in expected_date_range and max_date not in expected_date_range:
                freshness_issues.append(
                    f"Date range {min_date}..{max_date} does not align with "
                    f"expected '{expected_date_range}'"
                )

        passed = len(invalid_dates) == 0 and len(freshness_issues) == 0
        all_issues = invalid_dates + freshness_issues

        msg = (
            f"All trade_date values valid and fresh. Date range: {min_date} to {max_date}"
            if passed
            else f"Date freshness/validity issues detected: {len(all_issues)} issue(s)"
        )

        return (
            ValidationCheckResult(
                check_name="date_validity_and_freshness",
                severity=CheckSeverity.CRITICAL,
                passed=passed,
                message=msg,
                details={
                    "min_date": min_date,
                    "max_date": max_date,
                    "today": today_iso,
                    "invalid_dates": invalid_dates[:5],
                    "freshness_issues": freshness_issues,
                },
            ),
            min_date,
            max_date,
        )
