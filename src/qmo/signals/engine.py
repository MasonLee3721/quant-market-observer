"""Strategy filtering and signal generation engine."""

from typing import Any, Dict, List


def generate_leader_breakout_signals(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Select stocks conforming to Leader Breakout strategy.

    Criteria:
    - state == "leader"
    - stock_score >= 75.0
    - above_ma60 is True
    """
    signals = []
    for s in stocks:
        if (
            s.get("state") == "leader"
            and s.get("stock_score", 0.0) >= 75.0
            and s.get("above_ma60") is True
        ):
            signals.append(
                {
                    "stock_id": s.get("stock_id"),
                    "strategy": "leader_breakout",
                    "score": s.get("stock_score"),
                    "reason": "Leader stock with strong momentum above MA60",
                }
            )
    return signals


def generate_emerging_accumulation_signals(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Select stocks conforming to Emerging Accumulation strategy.

    Criteria:
    - state == "emerging"
    - ret_20d > 0
    - ret_20d_pct >= 50.0
    """
    signals = []
    for s in stocks:
        ret_20d = s.get("ret_20d")
        ret_20d_pct = s.get("ret_20d_pct")
        if (
            s.get("state") == "emerging"
            and ret_20d is not None
            and ret_20d > 0
            and ret_20d_pct is not None
            and ret_20d_pct >= 50.0
        ):
            signals.append(
                {
                    "stock_id": s.get("stock_id"),
                    "strategy": "emerging_accumulation",
                    "score": s.get("stock_score"),
                    "reason": "Emerging stock with institutional accumulation",
                }
            )
    return signals


def generate_risk_warning_signals(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identify leveraged risk warning stocks.

    Criteria:
    - state == "leveraged"
    """
    warnings = []
    for s in stocks:
        if s.get("state") == "leveraged":
            warnings.append(
                {
                    "stock_id": s.get("stock_id"),
                    "strategy": "risk_warning",
                    "score": s.get("stock_score"),
                    "reason": "High margin balance expansion with low institutional support",
                }
            )
    return warnings
