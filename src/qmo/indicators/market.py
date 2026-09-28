"""Market breadth and overall market score calculation functions."""

from typing import Optional, Sequence


def calculate_market_breadth(above_ma: Sequence[Optional[bool]]) -> Optional[float]:
    """Calculate market breadth: ratio of stocks with above_ma=True among non-null stocks."""
    valid_flags = [f for f in above_ma if f is not None]
    if not valid_flags:
        return None
    true_count = sum(1 for f in valid_flags if f is True)
    return round(true_count / len(valid_flags), 4)


def calculate_market_score(
    index_trend_score: float,
    breadth_score: float,
    turnover_heat_score: float,
    inst_direction_score: float,
    low_margin_score: float,
) -> float:
    """Calculate weighted composite market score (0-100).

    Weights:
    - Index trend: 30%
    - Market breadth: 25%
    - Turnover heat: 15%
    - Institutional direction: 20%
    - Low margin quality: 10%
    """
    score = (
        0.30 * index_trend_score
        + 0.25 * breadth_score
        + 0.15 * turnover_heat_score
        + 0.20 * inst_direction_score
        + 0.10 * low_margin_score
    )
    return round(max(0.0, min(100.0, score)), 2)
