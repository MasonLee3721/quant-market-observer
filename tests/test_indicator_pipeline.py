"""End-to-end integration tests for IndicatorPipelineRunner."""

import json
from pathlib import Path

from qmo.indicators.pipeline import IndicatorPipelineRunner


def test_indicator_pipeline_runner_execution(tmp_path: Path) -> None:
    """Verify end-to-end indicator calculation pipeline with sample data."""
    prices_data = [
        {"stock_id": "2330", "trade_date": "2026-09-20", "close_price": 100.0},
        {"stock_id": "2330", "trade_date": "2026-09-21", "close_price": 102.0},
        {"stock_id": "2330", "trade_date": "2026-09-25", "close_price": 110.0},
        {"stock_id": "2317", "trade_date": "2026-09-20", "close_price": 50.0},
        {"stock_id": "2317", "trade_date": "2026-09-25", "close_price": 48.0},
    ]

    runner = IndicatorPipelineRunner(root_dir=tmp_path)
    res = runner.run_pipeline(
        prices_data=prices_data,
        inst_data=[],
        margin_data=[],
        date_str="2026-09-25",
    )

    assert res["batch_id"] == "b_ind_20260925"
    assert res["processed_stocks"] == 2
    assert "market_score" in res
    assert "market_breadth_20" in res

    # Verify persistence
    summary_file = tmp_path / "indicators" / "b_ind_20260925" / "summary.json"
    assert summary_file.exists()

    payload = json.loads(summary_file.read_text())
    assert payload["batch_id"] == "b_ind_20260925"
    assert len(payload["stocks"]) == 2
