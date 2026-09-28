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
                    "strategy": "領頭羊突破策略 (Leader Breakout)",
                    "score": s.get("stock_score"),
                    "reason": "強勢領頭標的，站上 60 日季線且價格動能強勁",
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
                    "strategy": "新興積累策略 (Emerging Accumulation)",
                    "score": s.get("stock_score"),
                    "reason": "新興積累標的，法人資金持續卡位且中短期報酬為正",
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
                    "strategy": "高槓桿風險警訊 (Risk Warning)",
                    "score": s.get("stock_score"),
                    "reason": "散戶融資快速升溫，欠缺法人買超保護之高槓桿標的",
                }
            )
    return warnings
