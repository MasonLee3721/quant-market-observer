"""Theme/Industry rotation and fund concentration metrics calculation functions."""

from typing import Dict, Optional, Sequence


def calculate_flow_concentration(inflows: Sequence[float]) -> Dict[str, Optional[float]]:
    """Calculate concentration metrics for positive fund inflows.

    Returns dict containing:
    - top1_share: Top 1 inflow / Total positive inflows
    - top2_share: Top 2 inflows / Total positive inflows
    - flow_hhi: Herfindahl-Hirschman Index sum(share_i^2)
    """
    pos_inflows = [f for f in inflows if f > 0]
    if not pos_inflows:
        return {"top1_share": None, "top2_share": None, "flow_hhi": None}

    total_inflow = sum(pos_inflows)
    if total_inflow == 0:
        return {"top1_share": None, "top2_share": None, "flow_hhi": None}

    sorted_inflows = sorted(pos_inflows, reverse=True)
    shares = [f / total_inflow for f in sorted_inflows]

    top1 = shares[0] if len(shares) >= 1 else 0.0
    top2 = sum(shares[:2]) if len(shares) >= 2 else top1
    hhi = sum(s ** 2 for s in shares)

    return {
        "top1_share": round(top1, 4),
        "top2_share": round(top2, 4),
        "flow_hhi": round(hhi, 4),
    }


def calculate_theme_score(
    flow_score: float,
    relative_strength_score: float,
    breadth_score: float,
    turnover_score: float,
    low_margin_score: float,
) -> float:
    """Calculate composite Theme Score (0-100).

    Weights:
    - Fund flow: 30%
    - Relative strength: 25%
    - Theme breadth: 20%
    - Turnover ratio: 15%
    - Low margin quality: 10%
    """
    score = (
        0.30 * flow_score
        + 0.25 * relative_strength_score
        + 0.20 * breadth_score
        + 0.15 * turnover_score
        + 0.10 * low_margin_score
    )
    return round(max(0.0, min(100.0, score)), 2)
