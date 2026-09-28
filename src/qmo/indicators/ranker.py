"""Cross-sectional percentile ranking and stock state classification module."""

from enum import Enum
from typing import List, Optional, Sequence


class StockState(str, Enum):
    """Categorical status of stock under quantitative evaluation."""

    LEADER = "leader"
    EMERGING = "emerging"
    LEVERAGED = "leveraged"
    WATCH = "watch"
    EXCLUDED = "excluded"


def calculate_percentiles(values: Sequence[Optional[float]]) -> List[Optional[float]]:
    """Compute cross-sectional percentile score (0.0 to 100.0) for non-null values."""
    n = len(values)
    valid_pairs = [(i, v) for i, v in enumerate(values) if v is not None]
    if not valid_pairs:
        return [None] * n

    sorted_pairs = sorted(valid_pairs, key=lambda x: x[1])
    m = len(sorted_pairs)

    res: List[Optional[float]] = [None] * n
    for rank_idx, (orig_idx, _) in enumerate(sorted_pairs):
        pct = (rank_idx / (m - 1) * 100.0) if m > 1 else 50.0
        res[orig_idx] = round(pct, 2)

    return res


def calculate_stock_score(
    inst_flow_score: float,
    momentum_score: float,
    liquidity_score: float,
    risk_quality_score: float,
) -> float:
    """Calculate composite stock score (0-100).

    Weights:
    - Institutional flow: 35%
    - Momentum: 30%
    - Liquidity: 20%
    - Risk quality: 15%
    """
    score = (
        0.35 * inst_flow_score
        + 0.30 * momentum_score
        + 0.20 * liquidity_score
        + 0.15 * risk_quality_score
    )
    return round(max(0.0, min(100.0, score)), 2)


def classify_stock_state(
    ret_20d: Optional[float],
    above_ma60: Optional[bool],
    theme_rank_pct: Optional[float],
    stock_rank_pct: Optional[float],
    inst_flow_pct: Optional[float],
    margin_chg_pct: Optional[float],
    is_eligible: bool = True,
) -> StockState:
    """Classify stock into 5 states: leader, emerging, leveraged, watch, excluded."""
    if not is_eligible or ret_20d is None or above_ma60 is None:
        return StockState.EXCLUDED

    # Leader: theme top 20%, stock top 20%, ret_20d > 0, above_ma60
    if (
        (theme_rank_pct is not None and theme_rank_pct >= 80.0)
        and (stock_rank_pct is not None and stock_rank_pct >= 80.0)
        and ret_20d > 0
        and above_ma60 is True
    ):
        return StockState.LEADER

    # Emerging: 5d flow score top 20%, ret_20d between median & top 30%
    if (
        (inst_flow_pct is not None and inst_flow_pct >= 80.0)
        and ret_20d > 0
        and (stock_rank_pct is not None and 50.0 <= stock_rank_pct < 70.0)
    ):
        return StockState.EMERGING

    # Leveraged: momentum > 0, margin chg top 10%, inst flow < median
    if (
        ret_20d > 0
        and (margin_chg_pct is not None and margin_chg_pct >= 90.0)
        and (inst_flow_pct is None or inst_flow_pct < 50.0)
    ):
        return StockState.LEVERAGED

    return StockState.WATCH
