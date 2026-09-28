"""Unit tests for QMO signals and report generator modules."""

from qmo.reports.generator import generate_html_report, generate_markdown_report
from qmo.signals.engine import (
    generate_emerging_accumulation_signals,
    generate_leader_breakout_signals,
    generate_risk_warning_signals,
)
from qmo.signals.portfolio import allocate_portfolio


def test_strategy_signal_generation() -> None:
    """Verify leader, emerging, and risk warning strategy filters."""
    stocks = [
        {"stock_id": "2330", "state": "leader", "stock_score": 85.0, "above_ma60": True},
        {
            "stock_id": "2317",
            "state": "emerging",
            "stock_score": 60.0,
            "ret_20d": 0.05,
            "ret_20d_pct": 60.0,
        },
        {"stock_id": "2454", "state": "leveraged", "stock_score": 40.0},
    ]

    leaders = generate_leader_breakout_signals(stocks)
    assert len(leaders) == 1
    assert leaders[0]["stock_id"] == "2330"

    emergings = generate_emerging_accumulation_signals(stocks)
    assert len(emergings) == 1
    assert emergings[0]["stock_id"] == "2317"

    warnings = generate_risk_warning_signals(stocks)
    assert len(warnings) == 1
    assert warnings[0]["stock_id"] == "2454"


def test_portfolio_allocation() -> None:
    """Verify equal weighting portfolio allocation."""
    signals = [
        {"stock_id": "2330", "strategy": "leader_breakout", "score": 90.0},
        {"stock_id": "2317", "strategy": "emerging_accumulation", "score": 70.0},
    ]

    portfolio = allocate_portfolio(signals, max_positions=5)
    assert len(portfolio) == 2
    assert portfolio[0]["target_weight"] == 0.5
    assert portfolio[0]["stop_loss_pct"] == -0.07


def test_report_generation() -> None:
    """Verify Markdown and HTML report generation."""
    summary = {
        "date": "2026-09-28",
        "market_score": 75.0,
        "market_breadth_20": 0.8,
        "processed_stocks": 2,
    }
    signals = [{"stock_id": "2330", "strategy": "leader_breakout", "score": 90.0, "reason": "L"}]
    portfolio = [
        {"stock_id": "2330", "target_weight": 1.0, "stop_loss_pct": -0.07, "take_profit_pct": 0.15}
    ]

    md_report = generate_markdown_report(summary, signals, portfolio)
    assert "# Quant Market Observer 每日量化市場觀測報告" in md_report
    assert "`2330`" in md_report

    html_report = generate_html_report(summary, signals, portfolio)
    assert "<!DOCTYPE html>" in html_report
    assert "Quant Market Observer 每日量化市場觀測儀表板" in html_report
