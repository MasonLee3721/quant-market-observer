"""Unit tests for QMO indicator calculation engine functions."""

from typing import List, Optional

from qmo.indicators.features import (
    calculate_buy_streak,
    calculate_drawdown_60d,
    calculate_returns,
    calculate_sma,
    calculate_volatility_20d,
)
from qmo.indicators.market import calculate_market_breadth, calculate_market_score
from qmo.indicators.ranker import (
    StockState,
    calculate_percentiles,
    calculate_stock_score,
    classify_stock_state,
)
from qmo.indicators.themes import calculate_flow_concentration, calculate_theme_score


def test_calculate_returns() -> None:
    """Verify return calculations over lag periods."""
    prices: List[Optional[float]] = [100.0, 102.0, 105.0, 104.0, 110.0, 115.0]
    ret_5d = calculate_returns(prices, 5)
    assert ret_5d[0] is None
    assert ret_5d[4] is None
    assert ret_5d[5] == 0.15


def test_calculate_sma_and_volatility() -> None:
    """Verify SMA calculation with min_periods null handling."""
    prices: List[Optional[float]] = [10.0, 20.0, 30.0, 40.0, 50.0]
    sma_3d = calculate_sma(prices, 3)
    assert sma_3d[0] is None
    assert sma_3d[1] is None
    assert sma_3d[2] == 20.0
    assert sma_3d[4] == 40.0


def test_calculate_buy_streak() -> None:
    """Verify consecutive buy streak counter."""
    nets: List[Optional[float]] = [100, 200, -50, 300, 400, 500]
    streaks = calculate_buy_streak(nets)
    assert streaks == [1, 2, 0, 1, 2, 3]


def test_market_breadth_and_score() -> None:
    """Verify market breadth ratio and weighted market score."""
    flags: List[Optional[bool]] = [True, True, False, None, True]
    breadth = calculate_market_breadth(flags)
    assert breadth == 0.75

    score = calculate_market_score(80.0, 70.0, 60.0, 90.0, 50.0)
    # 0.30*80 + 0.25*70 + 0.15*60 + 0.20*90 + 0.10*50 = 24 + 17.5 + 9 + 18 + 5 = 73.5
    assert score == 73.5


def test_flow_concentration() -> None:
    """Verify Herfindahl-Hirschman Index and Top shares for inflows."""
    inflows = [100.0, 300.0, 600.0, -200.0]
    res = calculate_flow_concentration(inflows)
    assert res["top1_share"] == 0.6  # 600 / 1000
    assert res["top2_share"] == 0.9  # 900 / 1000
    assert res["flow_hhi"] == 0.46   # 0.6^2 + 0.3^2 + 0.1^2 = 0.36 + 0.09 + 0.01 = 0.46


def test_percentile_and_stock_classification() -> None:
    """Verify cross-sectional percentile scaling and stock state classification."""
    vals: List[Optional[float]] = [10.0, None, 30.0, 20.0]
    pcts = calculate_percentiles(vals)
    assert pcts[0] == 0.0
    assert pcts[1] is None
    assert pcts[3] == 50.0
    assert pcts[2] == 100.0

    state_leader = classify_stock_state(
        ret_20d=0.1,
        above_ma60=True,
        theme_rank_pct=85.0,
        stock_rank_pct=90.0,
        inst_flow_pct=85.0,
        margin_chg_pct=20.0,
    )
    assert state_leader == StockState.LEADER


def test_volatility_and_drawdown() -> None:
    """Verify 20d volatility and 60d drawdown calculations."""
    returns = [0.01] * 20
    vol = calculate_volatility_20d(returns)
    assert vol[18] is None
    assert vol[19] == 0.0

    prices = [100.0] * 59 + [120.0]
    dd = calculate_drawdown_60d(prices)
    assert dd[58] is None
    assert dd[59] == 0.0


def test_theme_and_stock_scores() -> None:
    """Verify theme score and stock score calculation weighting."""
    t_score = calculate_theme_score(80.0, 70.0, 60.0, 90.0, 50.0)
    assert t_score == 72.0

    s_score = calculate_stock_score(80.0, 70.0, 60.0, 50.0)
    # 0.35*80 + 0.30*70 + 0.20*60 + 0.15*50 = 28 + 21 + 12 + 7.5 = 68.5
    assert s_score == 68.5


def test_stock_state_classification_states() -> None:
    """Verify emerging, leveraged, watch, and excluded state classifications."""
    assert classify_stock_state(None, True, 50.0, 50.0, 50.0, 50.0) == StockState.EXCLUDED

    emerging = classify_stock_state(0.05, True, 50.0, 60.0, 85.0, 10.0)
    assert emerging == StockState.EMERGING

    leveraged = classify_stock_state(0.05, True, 50.0, 40.0, 40.0, 95.0)
    assert leveraged == StockState.LEVERAGED

    watch = classify_stock_state(0.05, True, 50.0, 40.0, 40.0, 10.0)
    assert watch == StockState.WATCH


def test_look_ahead_safety() -> None:
    """Verify point-in-time calculation safety (no look-ahead bias)."""
    prices = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0]
    ret_5d_t5 = calculate_returns(prices[:6], 5)[5]
    # Appending a future T+6 price must not alter T+5 return
    prices_with_future = prices + [200.0]
    ret_5d_t5_future = calculate_returns(prices_with_future, 5)[5]
    assert ret_5d_t5 == ret_5d_t5_future == 0.10


def test_null_handling_strictness() -> None:
    """Verify null values are preserved and not zero-filled in rolling calculations."""
    prices_with_null: List[Optional[float]] = [100.0, None, 105.0, 110.0, 115.0]
    sma_3d = calculate_sma(prices_with_null, 3)
    assert sma_3d[1] is None
    assert sma_3d[2] is None  # Includes index 1 which is None


def test_division_by_zero_and_edge_cases() -> None:
    """Verify zero division and empty inputs produce safe None/empty results."""
    zero_prices: List[Optional[float]] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert calculate_returns(zero_prices, 5)[5] is None

    negative_flows = [-100.0, -200.0, -50.0]
    hhi_res = calculate_flow_concentration(negative_flows)
    assert hhi_res["flow_hhi"] is None
    assert hhi_res["top1_share"] is None


def test_score_clamping_bounds() -> None:
    """Verify market and theme scores clamp strictly to [0.0, 100.0]."""
    high_market = calculate_market_score(120.0, 110.0, 130.0, 100.0, 100.0)
    low_market = calculate_market_score(-50.0, -20.0, 0.0, 0.0, 0.0)
    assert high_market == 100.0
    assert low_market == 0.0


