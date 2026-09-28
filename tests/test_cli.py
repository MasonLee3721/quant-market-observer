"""Tests for QMO CLI commands and option workflows."""

from pathlib import Path

from click.testing import CliRunner

from qmo import __version__
from qmo.cli import main
from qmo.models.price import DailyPrice
from qmo.storage.publisher import AtomicBatchPublisher


def test_cli_version() -> None:
    """Verify --version flag outputs CLI version."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_status_with_root_dir(tmp_path: Path) -> None:
    """Verify qmo status displays storage summary."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
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
    publisher.publish_batch(
        batch_id="b_status_test",
        dataset="daily_price",
        models=models,
        source_raw_hashes=["a" * 64],
    )

    runner = CliRunner()
    result = runner.invoke(main, ["status", "--root-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Quant Market Observer Status" in result.output
    assert "b_status_test" in result.output


def test_cli_update_dry_run(tmp_path: Path) -> None:
    """Verify qmo update with --dry-run option."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["update", "--date", "2026-09-27", "--dry-run", "--root-dir", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "[DRY-RUN]" in result.output


def test_cli_validate_formats(tmp_path: Path) -> None:
    """Verify qmo validate with text, json, and markdown formats."""
    publisher = AtomicBatchPublisher(root_dir=tmp_path)
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
    publisher.publish_batch(
        batch_id="b_val_test",
        dataset="daily_price",
        models=models,
        source_raw_hashes=["a" * 64],
    )

    runner = CliRunner()

    # Text format
    res_text = runner.invoke(main, ["validate", "--root-dir", str(tmp_path), "--format", "text"])
    assert res_text.exit_code == 0
    assert "Validated 1 quality report(s)" in res_text.output

    # JSON format
    res_json = runner.invoke(main, ["validate", "--root-dir", str(tmp_path), "--format", "json"])
    assert res_json.exit_code == 0
    assert '"batch_id": "b_val_test"' in res_json.output

    # Markdown format
    res_md = runner.invoke(
        main, ["validate", "--root-dir", str(tmp_path), "--format", "markdown"]
    )
    assert res_md.exit_code == 0
    assert "# Quality Validation Report" in res_md.output


def test_cli_help() -> None:
    """Verify help message when invoking main without subcommand."""
    runner = CliRunner()
    result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "Quant Market Observer (QMO) CLI." in result.output


def test_cli_validate_no_reports(tmp_path: Path) -> None:
    """Verify validate command handling when no reports exist."""
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--root-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No registered quality reports found" in result.output


def test_cli_update_datasets(tmp_path: Path) -> None:
    """Verify update command with dataset parameter."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["update", "--dataset", "daily_price", "--date", "2026-09-25", "--root-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Executing pipeline update" in result.output
    assert "Processing dataset 'daily_price'" in result.output


