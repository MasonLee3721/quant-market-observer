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
    res_md = runner.invoke(main, ["validate", "--root-dir", str(tmp_path), "--format", "markdown"])
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
        [
            "update",
            "--dataset",
            "daily_price",
            "--date",
            "2026-09-25",
            "--synthetic",
            "--root-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "Executing pipeline update" in result.output
    assert "Processing dataset 'daily_price'" in result.output


def test_cli_calculate(tmp_path: Path) -> None:
    """Verify qmo calculate command execution."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["calculate", "--date", "2026-09-28", "--root-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Executing indicator calculation pipeline" in result.output
    assert "Indicator Calculation Summary" in result.output


def test_cli_signal(tmp_path: Path) -> None:
    """Verify qmo signal command execution."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["signal", "--date", "2026-09-28", "--root-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Generating strategy signals" in result.output
    assert "Active Signals Count" in result.output


def test_cli_report(tmp_path: Path) -> None:
    """Verify qmo report command execution."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["report", "--date", "2026-09-28", "--format", "markdown", "--root-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Quant Market Observer 每日量化市場觀測報告" in result.output


def test_cli_update_official_bulk_e2e(tmp_path: Path) -> None:
    """Verify qmo update official-bulk mode E2E workflow."""
    from unittest.mock import MagicMock, patch

    from qmo.providers.transport import HttpResponse
    from qmo.storage.catalog import DuckDBCatalog

    fx_dir = Path("tests/fixtures/official")
    fixtures_map = {
        "MI_INDEX": (fx_dir / "twse_price_mi_index_20260924.json").read_bytes(),
        "stk_quote_result.php": (fx_dir / "tpex_price_stk_quote_20260924.json").read_bytes(),
        "fund/T86": (fx_dir / "twse_inst_t86_20260924.json").read_bytes(),
        "insti/dailyTrade": (fx_dir / "tpex_inst_dailyTrade_20260924.json").read_bytes(),
        "MI_MARGN": (fx_dir / "twse_margin_mimargn_20260924.json").read_bytes(),
        "margin/balance": (fx_dir / "tpex_margin_balance_20260924.json").read_bytes(),
    }

    mock_execute = MagicMock()

    def side_effect(url: str, params: dict | None = None) -> HttpResponse:
        for key, body in fixtures_map.items():
            if key in url:
                return HttpResponse(
                    status_code=200,
                    headers={"content-type": "application/json"},
                    raw_bytes=body,
                )
        raise ValueError(f"Unexpected URL: {url}")

    mock_execute.side_effect = side_effect

    runner = CliRunner()

    with patch("qmo.providers.transport.HttpTransport.execute", mock_execute):
        # 1. First run: cold execution
        res1 = runner.invoke(
            main,
            [
                "update",
                "--provider-mode",
                "official-bulk",
                "--date",
                "2026-09-24",
                "--root-dir",
                str(tmp_path),
            ],
        )
        assert res1.exit_code == 0, f"CLI update failed: {res1.output}"
        assert mock_execute.call_count == 6  # Exactly 6 requests (3 TWSE + 3 TPEx)

        # Verify DuckDB Catalog registered batches
        catalog = DuckDBCatalog(tmp_path / "catalog" / "qmo_catalog.duckdb")
        for ds in ["daily_price", "institutional_flow", "margin"]:
            batches = catalog.list_published_batches(ds)
            assert len(batches) == 1
            assert batches[0]["record_count"] > 0

        # Verify Raw Snapshots exist
        raw_files = list((tmp_path / "raw").rglob("*.json"))
        assert len(raw_files) == 6

        # 2. Second run with --resume: should hit cache with 0 new HTTP requests
        mock_execute.reset_mock()
        res2 = runner.invoke(
            main,
            [
                "update",
                "--provider-mode",
                "official-bulk",
                "--date",
                "2026-09-24",
                "--resume",
                "--root-dir",
                str(tmp_path),
            ],
        )
        assert res2.exit_code == 0
        assert mock_execute.call_count == 0  # 100% cache hits from RawSnapshotStore!
