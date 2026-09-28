"""Comprehensive unit tests for WP5 Validator and Official Reconciliation modules."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from qmo.models.institutional import InstitutionalFlow
from qmo.models.margin import Margin
from qmo.models.price import DailyPrice
from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.publisher import AtomicBatchPublisher
from qmo.validation import (
    BatchValidator,
    CheckSeverity,
    OfficialReconciler,
    QualityGateError,
    QualityReport,
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


def test_validator_detects_dataset_model_binding_mismatch() -> None:
    """Verify passing mismatched model class for a dataset fails quality gate."""
    validator = BatchValidator()
    flow_model = InstitutionalFlow(
        trade_date="2026-09-25",
        stock_id="2330",
        foreign_buy=1000,
        foreign_sell=400,
        foreign_net=600,
    )

    # Passing InstitutionalFlow when dataset="daily_price" must fail quality gate!
    with pytest.raises(QualityGateError, match="Dataset-model binding violation"):
        validator.validate_batch(
            batch_id="b_binding_mismatch",
            dataset="daily_price",
            models=[flow_model],
        )


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


def test_margin_domain_boundary_checks() -> None:
    """Verify margin purchase balance exceeding quota fails domain boundary check."""
    validator = BatchValidator()
    invalid_margin = [
        Margin(
            trade_date="2026-09-25",
            stock_id="2330",
            margin_purchase_balance=1000,
            margin_purchase_quota=500,  # Balance > quota!
        )
    ]

    with pytest.raises(QualityGateError, match="margin_purchase_balance .* > quota"):
        validator.validate_batch(batch_id="b_bad_margin", dataset="margin", models=invalid_margin)


def test_validator_detects_future_dates_and_staleness() -> None:
    """Verify future trade dates and stale trade dates fail date freshness checks."""
    validator = BatchValidator(max_stale_days=7)
    future_date = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")

    future_model = [
        DailyPrice(
            trade_date=future_date,
            stock_id="2330",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]

    with pytest.raises(QualityGateError, match="future date"):
        validator.validate_batch(
            batch_id="b_future_date", dataset="daily_price", models=future_model
        )

    stale_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    stale_model = [
        DailyPrice(
            trade_date=stale_date,
            stock_id="2330",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]

    with pytest.raises(QualityGateError, match="stale by"):
        validator.validate_batch(batch_id="b_stale_date", dataset="daily_price", models=stale_model)


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
        "date": "2026-09-25",
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


def test_reconciler_fails_on_corrupted_raw_payload() -> None:
    """Verify OfficialReconciler fails CRITICAL when provided envelope contains invalid JSON."""
    corrupted_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=b"{invalid json bytes",
    )

    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            open_price=100.0,
            close_price=104.0,
            trading_volume=1000,
            trading_value=104000,
        )
    ]

    res = OfficialReconciler.reconcile_daily_prices(models, twse_envelope=corrupted_env)
    assert res.passed is False
    assert res.severity == CheckSeverity.CRITICAL
    assert "parsing failed" in res.message


def test_reconciler_fails_on_zero_sample_intersection() -> None:
    """Verify OfficialReconciler fails CRITICAL if raw envelope and models have 0 overlap."""
    twse_raw_payload = {
        "stat": "OK",
        "date": "2026-09-25",
        "fields": ["證券代號", "收盤價", "成交股數"],
        "data": [["2330", "104.00", "1,000"]],
    }
    twse_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=json.dumps(twse_raw_payload).encode("utf-8"),
    )

    # Models contain completely different stock_id ("9999")
    models_different = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="9999",
            open_price=100.0,
            close_price=104.0,
            trading_volume=1000,
            trading_value=104000,
        )
    ]

    res = OfficialReconciler.reconcile_daily_prices(models_different, twse_envelope=twse_env)
    assert res.passed is False
    assert res.severity == CheckSeverity.CRITICAL
    assert "Zero matching sample intersection" in res.message


def test_reconciler_institutional_and_margin() -> None:
    """Verify OfficialReconciler reconciliation for InstitutionalFlow and Margin datasets."""
    twse_inst_payload = {
        "stat": "OK",
        "date": "2026-09-25",
        "fields": ["證券代號", "三大法人買賣超股數"],
        "data": [["2330", "5000"]],
    }
    twse_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=json.dumps(twse_inst_payload).encode("utf-8"),
    )

    flow_models = [
        InstitutionalFlow(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            foreign_buy=10000,
            foreign_sell=5000,
            foreign_net=5000,
            total_net=5000,
        )
    ]

    res_inst = OfficialReconciler.reconcile_institutional_flow(flow_models, twse_envelope=twse_env)
    assert res_inst.passed is True
    assert res_inst.details["match_rate_pct"] == 100.0

    twse_margin_payload = {
        "stat": "OK",
        "date": "2026-09-25",
        "fields": ["股票代號", "融資今日餘額", "融券今日餘額"],
        "data": [["2330", "1200", "500"]],
    }
    twse_margin_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=json.dumps(twse_margin_payload).encode("utf-8"),
    )
    margin_models = [
        Margin(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            margin_purchase_balance=1200,
            short_sale_balance=500,
        )
    ]

    res_margin = OfficialReconciler.reconcile_margin(margin_models, twse_envelope=twse_margin_env)
    assert res_margin.passed is True
    assert res_margin.details["match_rate_pct"] == 100.0


def test_reconciliation_failure_triggers_quality_gate() -> None:
    """Verify failed official reconciliation in BatchValidator triggers QualityGateError."""
    validator = BatchValidator()
    twse_raw_payload = {
        "stat": "OK",
        "date": "2026-09-25",
        "fields": ["證券代號", "收盤價", "成交股數"],
        "data": [["2330", "500.00", "1,000"]],  # Official price is 500.00
    }
    twse_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=json.dumps(twse_raw_payload).encode("utf-8"),
    )

    models_mismatched = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=100.0,  # Normalized price is 100.00 (mismatch!)
            trading_volume=1000,
            trading_value=100000,
        )
    ]

    with pytest.raises(QualityGateError, match="reconciliation match rate"):
        validator.validate_batch(
            batch_id="b_recon_gate",
            dataset="daily_price",
            models=models_mismatched,
            twse_envelope=twse_env,
        )


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


def test_publisher_enforces_coverage_during_publish(tmp_path: Path) -> None:
    """Verify AtomicBatchPublisher enforces target_tickers coverage check during publish."""
    target_pool = ["2330", "2317", "2454"]
    validator = BatchValidator(strict_coverage=True)
    publisher = AtomicBatchPublisher(root_dir=tmp_path, validator=validator)

    # Only contains 2330, missing 2317 and 2454
    incomplete_models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]

    with pytest.raises(QualityGateError, match="Missing 2 ticker"):
        publisher.publish_batch(
            batch_id="b_pub_coverage",
            dataset="daily_price",
            models=incomplete_models,
            source_raw_hashes=[VALID_RAW_HASH],
            target_tickers=target_pool,
        )


def test_publisher_persists_quality_report_and_links_catalog(tmp_path: Path) -> None:
    """Verify AtomicBatchPublisher persists quality_report.json and .md and links to Catalog."""
    validator = BatchValidator()
    publisher = AtomicBatchPublisher(root_dir=tmp_path, validator=validator)

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
        )
    ]

    publisher.publish_batch(
        batch_id="b_pub_report",
        dataset="daily_price",
        models=models,
        source_raw_hashes=[VALID_RAW_HASH],
    )

    published_dir = tmp_path / "normalized" / "daily_price" / "b_pub_report"
    assert (published_dir / "quality_report.json").exists()
    assert (published_dir / "quality_report.md").exists()

    cat_report = publisher.catalog.get_quality_report("daily_price", "b_pub_report")
    assert cat_report is not None
    assert cat_report["overall_passed"] is True
    assert cat_report["batch_id"] == "b_pub_report"


def test_publisher_enforces_reconciliation_failure_blocking(tmp_path: Path) -> None:
    """Verify OfficialReconciler CRITICAL failure during publish_batch blocks directory swap."""
    validator = BatchValidator()
    publisher = AtomicBatchPublisher(root_dir=tmp_path, validator=validator)

    twse_raw_payload = {
        "stat": "OK",
        "date": "2026-09-25",
        "fields": ["證券代號", "收盤價", "成交股數"],
        "data": [["2330", "500.00", "1,000"]],  # Official price 500.00
    }
    twse_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=json.dumps(twse_raw_payload).encode("utf-8"),
    )

    mismatched_models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=100.0,  # Mismatch!
            trading_volume=1000,
            trading_value=100000,
        )
    ]

    with pytest.raises(QualityGateError, match="reconciliation match rate"):
        publisher.publish_batch(
            batch_id="b_pub_recon_fail",
            dataset="daily_price",
            models=mismatched_models,
            source_raw_hashes=[VALID_RAW_HASH],
            twse_envelope=twse_env,
        )

    target_dir = tmp_path / "normalized" / "daily_price" / "b_pub_recon_fail"
    assert not target_dir.exists()


def test_margin_arithmetic_balance_check() -> None:
    """Verify margin balance arithmetic validation detects incorrect previous balance arithmetic."""
    validator = BatchValidator()
    invalid_margin_calc = [
        Margin(
            trade_date="2026-09-25",
            stock_id="2330",
            margin_purchase_previous_balance=1000,
            margin_purchase_buy=500,
            margin_purchase_sell=200,
            margin_purchase_cash_redemption=100,
            margin_purchase_balance=9999,  # Mismatch! Expected 1000 + 500 - 200 - 100 = 1200
        )
    ]

    with pytest.raises(QualityGateError, match="margin_purchase_balance"):
        validator.validate_batch(
            batch_id="b_bad_margin_calc", dataset="margin", models=invalid_margin_calc
        )


def test_reconciler_mismatch_date_market_source() -> None:
    """Verify strict composite key (trade_date, stock_id, market) rejects date mismatch."""
    twse_raw_payload = {
        "stat": "OK",
        "date": "2026-09-24",  # Official date is 2026-09-24
        "fields": ["證券代號", "收盤價", "成交股數"],
        "data": [["2330", "104.00", "1,000"]],
    }
    twse_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=json.dumps(twse_raw_payload).encode("utf-8"),
    )

    models_different_date = [
        DailyPrice(
            trade_date="2026-09-25",  # Model date is 2026-09-25 (mismatch!)
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=104.0,
            trading_volume=1000,
            trading_value=104000,
        )
    ]

    res = OfficialReconciler.reconcile_daily_prices(models_different_date, twse_envelope=twse_env)
    assert res.passed is False
    assert res.severity == CheckSeverity.CRITICAL
    assert "Zero matching sample intersection" in res.message


def test_reconciler_partial_envelope_parsing_failure_fails_closed() -> None:
    """Verify OfficialReconciler fails closed if ANY provided envelope fails parsing."""
    twse_raw_payload = {
        "stat": "OK",
        "date": "2026-09-25",
        "fields": ["證券代號", "收盤價", "成交股數"],
        "data": [["2330", "104.00", "1,000"]],
    }
    twse_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=json.dumps(twse_raw_payload).encode("utf-8"),
    )
    corrupted_tpex_env = RawResponseEnvelope(
        provider_name="tpex",
        endpoint="https://example.com",
        params={},
        status_code=200,
        raw_body_bytes=b"corrupted json",
    )

    models = [
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

    res = OfficialReconciler.reconcile_daily_prices(
        models, twse_envelope=twse_env, tpex_envelope=corrupted_tpex_env
    )
    assert res.passed is False
    assert res.severity == CheckSeverity.CRITICAL
    assert "parsing failed" in res.message


def test_validator_date_range_one_end_out_of_bounds_fails() -> None:
    """Verify expected_date_range boundary check fails when max_date exceeds expected range."""
    validator = BatchValidator()
    models = [
        DailyPrice(
            trade_date="2026-09-26",  # Exceeds expected_end "2026-09-25"!
            stock_id="2330",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]

    with pytest.raises(QualityGateError, match="outside expected date range"):
        validator.validate_batch(
            batch_id="b_out_of_bounds",
            dataset="daily_price",
            models=models,
            expected_date_range="2026-09-01..2026-09-25",
        )


def test_publisher_quality_report_write_failure_causes_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify failure during QualityReport staging write triggers publish rollback."""

    def bad_to_json(*a: Any, **kw: Any) -> str:
        raise OSError("Disk write failed during report serialization")

    monkeypatch.setattr(QualityReport, "to_json", bad_to_json)

    validator = BatchValidator()
    publisher = AtomicBatchPublisher(root_dir=tmp_path, validator=validator)

    models = [
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

    with pytest.raises(Exception, match="Failed to persist QualityReport"):
        publisher.publish_batch(
            batch_id="b_report_write_fail",
            dataset="daily_price",
            models=models,
            source_raw_hashes=[VALID_RAW_HASH],
        )

    # Published directory must NOT exist after failure
    target_dir = tmp_path / "normalized" / "daily_price" / "b_report_write_fail"
    assert not target_dir.exists()


def test_reconciler_fails_closed_on_non_200_status_or_corrupted_numbers() -> None:
    """Verify OfficialReconciler fails closed on non-200 HTTP status and invalid numbers."""
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]

    # 1. Envelope HTTP status code 500
    raw_500 = json.dumps(
        {
            "data": [["2330", "105.0", "1000"]],
            "fields": ["證券代號", "收盤價", "成交股數"],
            "date": "20260925",
        }
    ).encode("utf-8")
    bad_status_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://test.twse.com",
        params={"date": "20260925"},
        status_code=500,
        raw_body_bytes=raw_500,
    )
    res_status = OfficialReconciler.reconcile_daily_prices(models, twse_envelope=bad_status_env)
    assert not res_status.passed
    assert "returned HTTP status 500" in res_status.message

    # 2. Corrupted non-numeric value in raw body ("corrupted_price")
    raw_corrupt = json.dumps(
        {
            "data": [["2330", "corrupted_price", "1000"]],
            "fields": ["證券代號", "收盤價", "成交股數"],
            "date": "20260925",
        }
    ).encode("utf-8")
    corrupt_num_env = RawResponseEnvelope(
        provider_name="twse",
        endpoint="https://test.twse.com",
        params={"date": "20260925"},
        status_code=200,
        raw_body_bytes=raw_corrupt,
    )
    res_corrupt = OfficialReconciler.reconcile_daily_prices(models, twse_envelope=corrupt_num_env)
    assert not res_corrupt.passed
    assert "parsing failed" in res_corrupt.message


def test_validator_supports_space_separated_date_range() -> None:
    """Verify expected_date_range accepts 'YYYY-MM-DD to YYYY-MM-DD' format."""
    validator = BatchValidator()
    models = [
        DailyPrice(
            trade_date="2026-09-25",
            stock_id="2330",
            market="TWSE",
            open_price=100.0,
            close_price=105.0,
            trading_volume=1000,
            trading_value=105000,
        )
    ]
    report = validator.validate_batch(
        batch_id="b_space_date",
        dataset="daily_price",
        models=models,
        expected_date_range="2026-09-01 to 2026-09-30",
    )
    assert report.overall_passed
