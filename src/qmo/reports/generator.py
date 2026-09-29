"""Report generator for Traditional Chinese Markdown summary and HTML dashboard."""

from typing import Any, Dict, List


def generate_markdown_report(
    summary: Dict[str, Any],
    signals: List[Dict[str, Any]],
    portfolio: List[Dict[str, Any]],
) -> str:
    """Generate Traditional Chinese Markdown market summary report."""
    date_str = summary.get("date", "N/A")
    m_score = summary.get("market_score", 0.0)
    breadth = float(summary.get("market_breadth_20") or 0.0)
    stocks = summary.get("stocks", [])

    state_counts = {"leader": 0, "emerging": 0, "leveraged": 0, "watch": 0, "excluded": 0}
    for s in stocks:
        st = s.get("state", "watch").lower()
        if st in state_counts:
            state_counts[st] += 1
        else:
            state_counts["watch"] += 1

    lines = [
        f"# Quant Market Observer 每日量化市場觀測報告 ({date_str})",
        "",
        "## 1. 市場整體狀態與總分",
        f"- **市場綜合總分 (Market Score)**：`{m_score}` / 100",
        f"- **20日月線廣度 (20D Breadth)**：`{breadth * 100:.1f}%`",
        f"- **已處理分析個股總數**：{summary.get('processed_stocks', len(stocks))}",
        "",
        "## 2. 五大個股狀態分佈 (Stock State Distribution)",
        "| 狀態類別 | 個股數量 | 戰略意涵說明 |",
        "|---|---|---|",
        f"| `強勢領頭 (LEADER)` | {state_counts['leader']} | "
        "具備強勁價格動能與 60 日季線支撐之主力攻堅標的 |",
        f"| `新興積累 (EMERGING)` | {state_counts['emerging']} | "
        "法人資金持續卡位、中短期報酬為正之蓄勢標的 |",
        f"| `槓桿警訊 (LEVERAGED)` | {state_counts['leveraged']} | "
        "融資高升溫但法人參與度低之高槓桿風險標的 |",
        f"| `觀察追蹤 (WATCH)` | {state_counts['watch']} | 滿足部分技術或籌碼訊號之觀察清單 |",
        (
            f"| `暫時剔除 (EXCLUDED)` | {state_counts['excluded']} | "
            "流動性不足或資料過期不符合評分門檻 |"
        ),
        "",
        "## 3. 高評分個股因子明細 (Top Rated Tickers)",
        "| 股票代號 | 股票名稱 | 狀態類別 | 綜合評分 | 20日報酬率 | 站上60日季線 |",
        "|---|---|---|---|---|---|",
    ]

    for s in stocks[:15]:
        ret_20 = float(s.get("ret_20d") or 0.0) * 100
        ma60_str = "✅ 是" if s.get("above_ma60") else "❌ 否"
        name_str = s.get("name") or s.get("stock_id")
        lines.append(
            f"| `{s.get('stock_id')}` | {name_str} | `{s.get('state')}` | "
            f"`{s.get('stock_score')}` | {ret_20:+.1f}% | {ma60_str} |"
        )

    lines.extend(
        [
            "",
            "## 4. 策略選股訊號 (Active Strategy Signals)",
            "| 股票代號 | 策略名稱 | 綜合評分 | 選股邏輯與原因 |",
            "|---|---|---|---|",
        ]
    )

    for sig in signals:
        lines.append(
            f"| `{sig.get('stock_id')}` | {sig.get('strategy')} | "
            f"{sig.get('score')} | {sig.get('reason')} |"
        )

    lines.extend(
        [
            "",
            "## 5. 建議投資組合配置與風控目標 (Portfolio Allocation & Risk Control)",
            "| 股票代號 | 目標資金權重 | 硬停損目標 | 階段停利目標 |",
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
    """Generate Traditional Chinese (zh-TW) HTML visual dashboard."""
    date_str = summary.get("date", "N/A")
    m_score = summary.get("market_score", 0.0)
    breadth = float(summary.get("market_breadth_20") or 0.0)
    stocks = summary.get("stocks", [])

    state_counts = {"leader": 0, "emerging": 0, "leveraged": 0, "watch": 0, "excluded": 0}
    for s in stocks:
        st = s.get("state", "watch").lower()
        if st in state_counts:
            state_counts[st] += 1
        else:
            state_counts["watch"] += 1

    stock_rows = "".join(
        f"<tr><td><code>{s.get('stock_id')}</code></td>"
        f"<td><strong>{s.get('name', s.get('stock_id'))}</strong></td>"
        f"<td><span class='badge badge-{s.get('state')}'>{s.get('state').upper()}</span></td>"
        f"<td><strong>{s.get('stock_score')}</strong></td>"
        f"<td>{float(s.get('ret_20d') or 0.0) * 100:+.1f}%</td>"
        f"<td>{'✅ 是' if s.get('above_ma60') else '❌ 否'}</td></tr>"
        for s in stocks[:15]
    )

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

    font_family = (
        '-apple-system, BlinkMacSystemFont, "SF Pro TC", "SF Pro Text", '
        '"PingFang TC", "Helvetica Neue", Arial, sans-serif'
    )
    grid_style = (
        "display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); "
        "gap: 1rem; margin-bottom: 1.5rem;"
    )
    h1_style = (
        "color: #38bdf8; border-bottom: 2px solid #334155; "
        "padding-bottom: 0.5rem; font-size: 1.8rem;"
    )
    code_style = (
        "background: #0f172a; padding: 0.2rem 0.4rem; "
        "border-radius: 4px; color: #f43f5e; font-weight: 600;"
    )
    badge_style = (
        "padding: 0.25rem 0.6rem; border-radius: 9999px; "
        "font-size: 0.8rem; font-weight: 700; text-transform: uppercase;"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant Market Observer 量化市場觀測儀表板 - {date_str}</title>
    <style>
        body {{
            font-family: {font_family};
            margin: 2rem;
            background: #0f172a;
            color: #f8fafc;
            line-height: 1.5;
        }}
        h1 {{ {h1_style} }}
        h2 {{ color: #94a3b8; font-size: 1.25rem; margin-top: 0; }}
        .grid {{ {grid_style} }}
        .card {{
            background: #1e293b;
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            border: 1px solid #334155;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        .stat-val {{ font-size: 2.2rem; font-weight: bold; color: #38bdf8; margin-top: 0.5rem; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #334155; color: #38bdf8; font-weight: 600; }}
        code {{ {code_style} }}
        .badge {{ {badge_style} }}
        .badge-leader {{ background: #059669; color: #ecfdf5; }}
        .badge-emerging {{ background: #0284c7; color: #f0f9ff; }}
        .badge-leveraged {{ background: #d97706; color: #fffbeb; }}
        .badge-watch {{ background: #475569; color: #f8fafc; }}
        .badge-excluded {{ background: #dc2626; color: #fef2f2; }}
    </style>
</head>
<body>
    <h1>Quant Market Observer 每日量化市場觀測儀表板 ({date_str})</h1>

    <div class="grid">
        <div class="card">
            <h2>市場綜合總分 (Market Score)</h2>
            <div class="stat-val">
                {m_score} <span style="font-size:1rem; color:#94a3b8;">/ 100</span>
            </div>
        </div>
        <div class="card">
            <h2>20日月線廣度 (20D Breadth)</h2>
            <div class="stat-val">{breadth * 100:.1f}%</div>
        </div>
        <div class="card">
            <h2>已處理個股總數</h2>
            <div class="stat-val">{summary.get("processed_stocks", len(stocks))}</div>
        </div>
    </div>

    <div class="card">
        <h2>五大個股狀態分佈 (Stock States Distribution)</h2>
        <table>
            <thead><tr><th>狀態類別</th><th>個股數量</th><th>戰略意涵說明</th></tr></thead>
            <tbody>
                <tr>
                    <td><span class="badge badge-leader">強勢領頭 LEADER</span></td>
                    <td><strong>{state_counts["leader"]}</strong></td>
                    <td>具備強勁價格動能與 60 日季線支撐之主力攻堅標的</td>
                </tr>
                <tr>
                    <td><span class="badge badge-emerging">新興積累 EMERGING</span></td>
                    <td><strong>{state_counts["emerging"]}</strong></td>
                    <td>法人資金持續卡位、中短期報酬為正之蓄勢標的</td>
                </tr>
                <tr>
                    <td><span class="badge badge-leveraged">槓桿警訊 LEVERAGED</span></td>
                    <td><strong>{state_counts["leveraged"]}</strong></td>
                    <td>融資高升溫但法人參與度低之高槓桿風險標的</td>
                </tr>
                <tr>
                    <td><span class="badge badge-watch">觀察追蹤 WATCH</span></td>
                    <td><strong>{state_counts["watch"]}</strong></td>
                    <td>滿足部分技術或籌碼訊號之觀察清單</td>
                </tr>
                <tr>
                    <td><span class="badge badge-excluded">暫時剔除 EXCLUDED</span></td>
                    <td><strong>{state_counts["excluded"]}</strong></td>
                    <td>流動性不足或資料過期不符合評分門檻</td>
                </tr>
            </tbody>
        </table>
    </div>

    <div class="card">
        <h2>高評分個股因子明細 (Top Rated Tickers Factor Breakdown)</h2>
        <table>
            <thead>
                <tr>
                    <th>股票代號</th><th>股票名稱</th><th>狀態類別</th>
                    <th>綜合評分</th><th>20日報酬率</th><th>站上60日季線</th>
                </tr>
            </thead>
            <tbody>{stock_rows}</tbody>
        </table>
    </div>

    <div class="card">
        <h2>策略選股訊號 (Active Strategy Signals)</h2>
        <table>
            <thead><tr><th>股票代號</th><th>策略名稱</th><th>綜合評分</th><th>選股邏輯與原因</th></tr></thead>
            <tbody>{sig_rows}</tbody>
        </table>
    </div>

    <div class="card">
        <h2>建議投資組合配置與風控目標 (Portfolio Allocation & Risk Control)</h2>
        <table>
            <thead>
                <tr><th>股票代號</th><th>目標資金權重</th><th>硬停損目標</th><th>階段停利目標</th></tr>
            </thead>
            <tbody>{port_rows}</tbody>
        </table>
    </div>
</body>
</html>
"""
