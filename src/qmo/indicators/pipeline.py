"""End-to-end indicator calculation pipeline runner module."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from qmo.indicators.features import (
    calculate_returns,
    calculate_sma,
)
from qmo.indicators.market import calculate_market_breadth, calculate_market_score
from qmo.indicators.ranker import (
    calculate_percentiles,
    calculate_stock_score,
    classify_stock_state,
)


class IndicatorPipelineRunner:
    """Orchestrates end-to-end factor computation and indicator persistence."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.indicators_dir = self.root_dir / "indicators"

    def run_pipeline(
        self,
        prices_data: Sequence[Dict[str, Any]],
        inst_data: Sequence[Dict[str, Any]],
        margin_data: Sequence[Dict[str, Any]],
        date_str: str = "latest",
    ) -> Dict[str, Any]:
        """Execute indicator calculation flow across stocks and market metrics."""
        # 1. Group prices by stock_id
        stocks: Dict[str, List[Dict[str, Any]]] = {}
        for row in prices_data:
            sid = str(row.get("stock_id", ""))
            if sid not in stocks:
                stocks[sid] = []
            stocks[sid].append(row)

        computed_stocks: Dict[str, Dict[str, Any]] = {}
        above_ma20_flags: List[Optional[bool]] = []

        for sid, rows in stocks.items():
            sorted_rows = sorted(rows, key=lambda x: str(x.get("trade_date", "")))
            closes = [r.get("close_price") for r in sorted_rows]

            ret_5d = calculate_returns(closes, 5)
            ret_20d = calculate_returns(closes, 20)
            ret_60d = calculate_returns(closes, 60)

            ma20 = calculate_sma(closes, 20)
            ma60 = calculate_sma(closes, 60)

            latest_idx = len(closes) - 1
            latest_close = closes[latest_idx] if latest_idx >= 0 else None
            latest_ma20 = ma20[latest_idx] if latest_idx < len(ma20) else None
            latest_ma60 = ma60[latest_idx] if latest_idx < len(ma60) else None

            above_ma20 = (
                (latest_close > latest_ma20)
                if (latest_close is not None and latest_ma20 is not None)
                else None
            )
            above_ma60 = (
                (latest_close > latest_ma60)
                if (latest_close is not None and latest_ma60 is not None)
                else None
            )
            above_ma20_flags.append(above_ma20)

            computed_stocks[sid] = {
                "stock_id": sid,
                "ret_5d": ret_5d[latest_idx] if latest_idx < len(ret_5d) else None,
                "ret_20d": ret_20d[latest_idx] if latest_idx < len(ret_20d) else None,
                "ret_60d": ret_60d[latest_idx] if latest_idx < len(ret_60d) else None,
                "above_ma20": above_ma20,
                "above_ma60": above_ma60,
            }

        # 2. Market Metrics
        breadth_20 = calculate_market_breadth(above_ma20_flags) or 0.5
        market_score = calculate_market_score(
            index_trend_score=70.0,
            breadth_score=breadth_20 * 100.0,
            turnover_heat_score=60.0,
            inst_direction_score=65.0,
            low_margin_score=70.0,
        )

        # 3. Cross-Sectional Ranking
        stock_ids = list(computed_stocks.keys())
        ret_20d_vals = [computed_stocks[s]["ret_20d"] for s in stock_ids]
        ret_20d_pcts = calculate_percentiles(ret_20d_vals)

        for idx, sid in enumerate(stock_ids):
            computed_stocks[sid]["ret_20d_pct"] = ret_20d_pcts[idx]
            computed_stocks[sid]["stock_score"] = calculate_stock_score(
                inst_flow_score=ret_20d_pcts[idx] or 50.0,
                momentum_score=ret_20d_pcts[idx] or 50.0,
                liquidity_score=50.0,
                risk_quality_score=50.0,
            )
            computed_stocks[sid]["state"] = classify_stock_state(
                ret_20d=computed_stocks[sid]["ret_20d"],
                above_ma60=computed_stocks[sid]["above_ma60"],
                theme_rank_pct=ret_20d_pcts[idx],
                stock_rank_pct=ret_20d_pcts[idx],
                inst_flow_pct=ret_20d_pcts[idx],
                margin_chg_pct=20.0,
            )

        # 4. Save to target storage
        batch_id = f"b_ind_{date_str.replace('-', '')}"
        batch_dir = self.indicators_dir / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)

        summary_file = batch_dir / "summary.json"
        result_payload = {
            "batch_id": batch_id,
            "date": date_str,
            "market_breadth_20": breadth_20,
            "market_score": market_score,
            "processed_stocks": len(computed_stocks),
            "stocks": list(computed_stocks.values()),
        }
        summary_file.write_text(json.dumps(result_payload, indent=2))

        return result_payload
