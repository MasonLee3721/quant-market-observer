"""Report generator for Markdown summary and HTML dashboard."""

from typing import Any, Dict, List


def generate_markdown_report(
    summary: Dict[str, Any],
    signals: List[Dict[str, Any]],
    portfolio: List[Dict[str, Any]],
) -> str:
    """Generate Markdown market summary report."""
    date_str = summary.get("date", "N/A")
    m_score = summary.get("market_score", 0.0)
    breadth = float(summary.get("market_breadth_20") or 0.0)

    lines = [
        f"# Quant Market Observer Daily Report ({date_str})",
        "",
        "## 1. Market Status",
        f"- **Market Composite Score**: `{m_score}` / 100",
        f"- **20D Market Breadth**: `{breadth * 100:.1f}%`",
        f"- **Processed Tickers**: {summary.get('processed_stocks', 0)}",
        "",
        "## 2. Strategy Signals",
        "| Ticker | Strategy | Score | Reason |",
        "|---|---|---|---|",
    ]

    for sig in signals:
        lines.append(
            f"| `{sig.get('stock_id')}` | {sig.get('strategy')} | "
            f"{sig.get('score')} | {sig.get('reason')} |"
        )

    lines.extend(
        [
            "",
            "## 3. Recommended Portfolio Allocation",
            "| Ticker | Target Weight | Stop Loss | Take Profit |",
            "|---|---|---|---|",
        ]
    )

    for pos in portfolio:
        tw = float(pos.get("target_weight") or 0.0) * 100
        sl = float(pos.get("stop_loss_pct") or 0.0) * 100
        tp = float(pos.get("take_profit_pct") or 0.0) * 100
        lines.append(f"| `{pos.get('stock_id')}` | {tw:.1f}% | {sl:.1f}% | +{tp:.1f}% |")

    lines.append("")
    return "\n".join(lines)


def generate_html_report(
    summary: Dict[str, Any],
    signals: List[Dict[str, Any]],
    portfolio: List[Dict[str, Any]],
) -> str:
    """Generate HTML visual dashboard report."""
    date_str = summary.get("date", "N/A")
    m_score = summary.get("market_score", 0.0)
    breadth = float(summary.get("market_breadth_20") or 0.0)

    sig_rows = "".join(
        f"<tr><td><code>{s.get('stock_id')}</code></td><td>{s.get('strategy')}</td>"
        f"<td>{s.get('score')}</td><td>{s.get('reason')}</td></tr>"
        for s in signals
    )

    port_rows = "".join(
        f"<tr><td><code>{p.get('stock_id')}</code></td>"
        f"<td>{float(p.get('target_weight') or 0.0) * 100:.1f}%</td>"
        f"<td>{float(p.get('stop_loss_pct') or 0.0) * 100:.1f}%</td>"
        f"<td>+{float(p.get('take_profit_pct') or 0.0) * 100:.1f}%</td></tr>"
        for p in portfolio
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>QMO Market Dashboard - {date_str}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 2rem;
            background: #0f172a;
            color: #f8fafc;
        }}
        h1 {{ color: #38bdf8; border-bottom: 2px solid #334155; padding-bottom: 0.5rem; }}
        .card {{
            background: #1e293b;
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            border: 1px solid #334155;
        }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #334155; color: #38bdf8; }}
        code {{ background: #0f172a; padding: 0.2rem 0.4rem; border-radius: 4px; color: #f43f5e; }}
    </style>
</head>
<body>
    <h1>Quant Market Observer Daily Dashboard</h1>
    <div class="card">
        <h2>Market Overview ({date_str})</h2>
        <p><strong>Market Score:</strong> {m_score} / 100</p>
        <p><strong>20D Market Breadth:</strong> {breadth * 100:.1f}%</p>
    </div>
    <div class="card">
        <h2>Active Strategy Signals</h2>
        <table>
            <thead><tr><th>Ticker</th><th>Strategy</th><th>Score</th><th>Reason</th></tr></thead>
            <tbody>{sig_rows}</tbody>
        </table>
    </div>
    <div class="card">
        <h2>Portfolio Allocation</h2>
        <table>
            <thead>
                <tr><th>Ticker</th><th>Weight</th><th>Stop Loss</th><th>Take Profit</th></tr>
            </thead>
            <tbody>{port_rows}</tbody>
        </table>
    </div>
</body>
</html>
"""
