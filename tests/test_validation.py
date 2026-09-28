"""Unit tests for WP5 Validator and Official Reconciliation modules."""

import json
from pathlib import Path

import pytest

from qmo.models.institutional import InstitutionalFlow
from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.publisher import AtomicBatchPublisher
from qmo.validation import (
    BatchValidator,
    CheckSeverity,
    OfficialReconciler,
    QualityGateError,
)

VALID_RAW_HASH = "a" * 64


def test_batch_validator_valid_models_pass() -> None:
    """Verify valid models pass all batch validation checks cleanly."""
    validator = BatchValidator()
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            high_price=105.0,
            low_price=99.0,
            close_price=104.0,
            trading_volume=1000,
            trading_value=104000,
            source="FinMind:TaiwanStockPrice",
        ),
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="8069",
            market="TPEx",
            open_price=50.0,
            high_price=52.0,
            low_price=49.0,
            close_price=51.0,
            trading_volume=500,
            trading_value=25500,
            source="FinMind:TaiwanStockPrice",
        ),
    ]

    report = validator.validate_batch(
        batch_id="b_valid",
        dataset="daily_price",
        models=models,
        target_tickers=["2330", "8069"],
    )

    assert report.overall_passed is True
    assert report.summary["passed_checks"] == report.summary["total_checks"]
    assert report.summary["total_records"] == 2
    assert report.summary["unique_stocks"] == 2


def test_batch_validator_detects_duplicate_primary_keys() -> None:
    """Verify duplicate (trade_date, stock_id) composite key fails quality gate."""
    validator = BatchValidator()
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        ),
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",  # Duplicate key!
            open_price=101.0,
            close_price=106.0,
            trading_volume=1200,
            trading_value=127200,
        ),
    ]

    with pytest.raises(QualityGateError, match="Duplicate primary key"):
        validator.validate_batch(batch_id="b_dup", dataset="daily_price", models=models)


def test_batch_validator_detects_domain_boundary_violations() -> None:
    """Verify high_price < low_price or negative prices fail domain boundary checks."""
    validator = BatchValidator()

    # Invalid high < low
    models_invalid_high_low = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            open_price=100.0,
            high_price=90.0,  # Invalid: high < low!
            low_price=95.0,
            close_price=92.0,
            trading_volume=1000,
            trading_value=92000,
        )
    ]

    with pytest.raises(QualityGateError, match="high_price .* < low_price"):
        validator.validate_batch(
            batch_id="b_bad_high_low", dataset="daily_price", models=models_invalid_high_low
        )

    # Invalid net calculation in institutional flow
    models_invalid_flow = [
        InstitutionalFlow(
            trade_date="2026-09-25",
            stock_id="2330",
            foreign_buy=1000,
            foreign_sell=400,
            foreign_net=9999,  # Mismatched net! (expected 600)
        )
    ]

    with pytest.raises(QualityGateError, match="foreign_net"):
        validator.validate_batch(
            batch_id="b_bad_flow", dataset="institutional_flow", models=models_invalid_flow
        )


def test_batch_validator_stock_ticker_coverage() -> None:
    """Verify strict_coverage=True raises QualityGateError if target tickers are missing."""
    target_50_tickers = [f"{i:04d}" for i in range(1, 51)]
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="0001",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]

    # Non-strict coverage produces a report with WARNING
    validator_lenient = BatchValidator(strict_coverage=False)
    report_lenient = validator_lenient.validate_batch(
        batch_id="b_coverage",
        dataset="daily_price",
        models=models,
        target_tickers=target_50_tickers,
        raise_on_failure=False,
    )
    assert report_lenient.overall_passed is True
    coverage_check = next(
        c for c in report_lenient.check_results if c.check_name == "stock_ticker_coverage"
    )
    assert coverage_check.severity == CheckSeverity.WARNING
    assert coverage_check.passed is False

    # Strict coverage fails quality gate
    validator_strict = BatchValidator(strict_coverage=True)
    with pytest.raises(QualityGateError, match="Missing .* ticker"):
        validator_strict.validate_batch(
            batch_id="b_coverage",
            dataset="daily_price",
            models=models,
            target_tickers=target_50_tickers,
        )


def test_official_reconciler_daily_prices() -> None:
    """Verify OfficialReconciler cross-checks normalized models against TWSE/TPEx raw envelopes."""
    twse_raw_payload = {
        "stat": "OK",
        "fields": [
            "證券代號",
            "證券名稱",
            "成交股數",
            "成交筆數",
            "成交金額",
            "開盤價",
            "最高價",
            "最低價",
            "收盤價",
        ],
        "data": [
            ["2330", "台積電", "1,000", "100", "104,000", "100.00", "105.00", "99.00", "104.00"]
        ],
    }

    twse_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=json.dumps(twse_raw_payload).encode("utf-8"),
    )

    models_matching = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=104.0,
            trading_volume=1000,
            trading_value=104000,
        )
    ]

    res_pass = OfficialReconciler.reconcile_daily_prices(models_matching, twse_envelope=twse_env)
    assert res_pass.passed is True
    assert res_pass.details["match_rate_pct"] == 100.0

    # Mismatched model
    models_mismatched = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=999.0,  # Mismatched price!
            trading_volume=1000,
            trading_value=104000,
        )
    ]

    res_fail = OfficialReconciler.reconcile_daily_prices(
        models_mismatched, twse_envelope=twse_env, min_match_rate_pct=99.5
    )
    assert res_fail.passed is False
    assert res_fail.details["mismatched_count"] == 1


def test_quality_report_formatting() -> None:
    """Verify QualityReport formatting to JSON and Markdown."""
    validator = BatchValidator()
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]

    report = validator.validate_batch(batch_id="b_report", dataset="daily_price", models=models)

    json_str = report.to_json()
    assert '"batch_id": "b_report"' in json_str

    md_str = report.to_markdown()
    assert "# Quality Validation Report: daily_price / b_report" in md_str
    assert "✅ PASSED" in md_str


def test_publisher_integration_with_validator(tmp_path: Path) -> None:
    """Verify AtomicBatchPublisher with validator blocks publishing when quality check fails."""
    validator = BatchValidator()
    publisher = AtomicBatchPublisher(root_dir=tmp_path, validator=validator)

    invalid_models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            open_price=100.0,
            high_price=80.0,  # Invalid high < low!
            low_price=90.0,
            close_price=85.0,
            trading_volume=1000,
            trading_value=85000,
        )
    ]

    with pytest.raises(QualityGateError, match="high_price .* < low_price"):
        publisher.publish_batch(
            batch_id="b_publisher_invalid",
            dataset="daily_price",
            models=invalid_models,
            source_raw_hashes=[VALID_RAW_HASH],
        )

    # Published directory must NOT exist after quality gate block
    target_dir = tmp_path / "normalized" / "daily_price" / "b_publisher_invalid"
    assert not target_dir.exists()
