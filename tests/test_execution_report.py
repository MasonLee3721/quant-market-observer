"""Tests for execution summary and failure list persistence."""

from pathlib import Path

import pytest

from qmo.storage.execution_report import (
    ExecutionFailureRecord,
    ExecutionSummaryReport,
    load_execution_summary,
    sanitize_sensitive_text,
    save_execution_summary,
)


def test_sanitize_sensitive_text() -> None:
    raw = "Failed HTTP 403 request url=https://api.test/data?token=secret123&data_id=2330"
    sanitized = sanitize_sensitive_text(raw)
    assert "token=***MASKED***" in sanitized
    assert "secret123" not in sanitized
    assert "data_id=2330" in sanitized


def test_execution_failure_record_post_init_masking() -> None:
    rec = ExecutionFailureRecord(
        stock_id="2330",
        error_type="ProviderError",
        error_message="HTTP 401 error with api_token=my_secret_token_val",
    )
    assert "my_secret_token_val" not in rec.error_message
    assert "api_token=***MASKED***" in rec.error_message


def test_execution_summary_report_persistence_roundtrip(tmp_path: Path) -> None:
    report = ExecutionSummaryReport(
        started_at="2026-09-28T12:00:00Z",
        ended_at="2026-09-28T12:05:00Z",
        dataset="daily_price",
        target_date="2026-09-24",
        universe_count=5,
        success_count=4,
        empty_data_count=0,
        failure_count=1,
        failures=[
            ExecutionFailureRecord(
                stock_id="8069",
                error_type="NetworkError",
                error_message="Timeout with token=abc_secret_123",
            )
        ],
        cache_hits=3,
        api_requests=2,
    )

    path = save_execution_summary(tmp_path, report)
    assert path.is_file()
    assert "execution_summary_daily_price_20260924.json" in path.name

    loaded = load_execution_summary(path)
    assert loaded.started_at == "2026-09-28T12:00:00Z"
    assert loaded.ended_at == "2026-09-28T12:05:00Z"
    assert loaded.dataset == "daily_price"
    assert loaded.target_date == "2026-09-24"
    assert loaded.universe_count == 5
    assert loaded.success_count == 4
    assert loaded.empty_data_count == 0
    assert loaded.failure_count == 1
    assert loaded.cache_hits == 3
    assert loaded.api_requests == 2
    assert len(loaded.failures) == 1
    assert loaded.failures[0].stock_id == "8069"
    assert "token=***MASKED***" in loaded.failures[0].error_message
    assert "abc_secret_123" not in loaded.failures[0].error_message


def test_invalid_dataset_name_fails_closed(tmp_path: Path) -> None:
    report = ExecutionSummaryReport(
        started_at="2026-09-28T12:00:00Z",
        ended_at="2026-09-28T12:05:00Z",
        dataset="../invalid_path",
        target_date="2026-09-24",
        universe_count=1,
        success_count=1,
        empty_data_count=0,
        failure_count=0,
        cache_hits=1,
        api_requests=0,
    )
    with pytest.raises(ValueError, match="Unsafe or invalid dataset"):
        save_execution_summary(tmp_path, report)
