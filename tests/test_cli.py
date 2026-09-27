"""Tests for QMO CLI."""

from click.testing import CliRunner

from qmo import __version__
from qmo.cli import main


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_status() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "Quant Market Observer Status" in result.output
    assert "M1 — Data Pipeline MVP" in result.output


def test_cli_update_shell() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["update", "--date", "2026-09-27"])
    assert result.exit_code == 0
    assert "2026-09-27" in result.output


def test_cli_validate_shell() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["validate"])
    assert result.exit_code == 0
    assert "Validating batch: latest" in result.output
