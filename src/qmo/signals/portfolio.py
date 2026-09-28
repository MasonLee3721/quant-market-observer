"""Portfolio allocation and risk management module."""

from typing import Any, Dict, List


def allocate_portfolio(
    signals: List[Dict[str, Any]], max_positions: int = 5
) -> List[Dict[str, Any]]:
    """Allocate equal weights to top N candidate signals sorted by score."""
    if not signals:
        return []

    sorted_signals = sorted(signals, key=lambda s: s.get("score", 0.0), reverse=True)
    selected = sorted_signals[:max_positions]
    target_weight = round(1.0 / len(selected), 4)

    portfolio = []
    for item in selected:
        portfolio.append(
            {
                "stock_id": item.get("stock_id"),
                "strategy": item.get("strategy"),
                "score": item.get("score"),
                "target_weight": target_weight,
                "stop_loss_pct": -0.07,
                "take_profit_pct": 0.15,
            }
        )
    return portfolio
