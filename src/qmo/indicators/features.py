"""Price, momentum, volatility, institutional, and leverage feature calculation functions."""

import math
from typing import List, Optional, Sequence


def calculate_returns(prices: Sequence[Optional[float]], lag: int) -> List[Optional[float]]:
    """Calculate lag-period return: close_t / close_{t-lag} - 1.

    Returns None if sample window is insufficient or if close_{t-lag} is None or zero.
    """
    n = len(prices)
    res: List[Optional[float]] = [None] * n
    for i in range(n):
        if i < lag:
            res[i] = None
            continue
        p_t = prices[i]
        p_prev = prices[i - lag]
        if p_t is None or p_prev is None or p_prev == 0:
            res[i] = None
        else:
            res[i] = round((p_t / p_prev) - 1.0, 6)
    return res


def calculate_sma(values: Sequence[Optional[float]], window: int) -> List[Optional[float]]:
    """Calculate Simple Moving Average over window.

    Returns None if non-null count < window.
    """
    n = len(values)
    res: List[Optional[float]] = [None] * n
    for i in range(n):
        if i < window - 1:
            res[i] = None
            continue
        sub = values[i - window + 1 : i + 1]
        if any(v is None for v in sub):
            res[i] = None
        else:
            res[i] = round(sum(v for v in sub if v is not None) / window, 6)
    return res


def calculate_volatility_20d(returns: Sequence[Optional[float]]) -> List[Optional[float]]:
    """Calculate 20-day annualized volatility: std(daily_return, 20) * sqrt(252)."""
    n = len(returns)
    res: List[Optional[float]] = [None] * n
    for i in range(n):
        if i < 19:
            res[i] = None
            continue
        sub = returns[i - 19 : i + 1]
        valid_vals = [v for v in sub if v is not None]
        if len(valid_vals) < 20:
            res[i] = None
        else:
            mean_val = sum(valid_vals) / 20.0
            variance = sum((v - mean_val) ** 2 for v in valid_vals) / 19.0  # sample std
            std_val = math.sqrt(variance)
            res[i] = round(std_val * math.sqrt(252), 6)
    return res


def calculate_drawdown_60d(prices: Sequence[Optional[float]]) -> List[Optional[float]]:
    """Calculate 60-day drawdown: close_t / rolling_max(close, 60) - 1."""
    n = len(prices)
    res: List[Optional[float]] = [None] * n
    for i in range(n):
        if i < 59:
            res[i] = None
            continue
        sub = prices[i - 59 : i + 1]
        if any(p is None for p in sub):
            res[i] = None
        else:
            max_p = max(p for p in sub if p is not None)
            p_t = prices[i]
            if p_t is None or max_p == 0:
                res[i] = None
            else:
                res[i] = round((p_t / max_p) - 1.0, 6)
    return res


def calculate_buy_streak(net_amounts: Sequence[Optional[float]]) -> List[int]:
    """Calculate consecutive buy days (net > 0) moving backward from current day."""
    n = len(net_amounts)
    res: List[int] = [0] * n
    current_streak = 0
    for i in range(n):
        val = net_amounts[i]
        if val is not None and val > 0:
            current_streak += 1
        else:
            current_streak = 0
        res[i] = current_streak
    return res
