"""Generator script for M0 Golden Fixtures and CI Synthetic 50-Ticker Sample Fixture."""

import csv
import hashlib
import json
import re
from pathlib import Path

ROOT_DIR = Path(__file__).parents[1]
UNIVERSE_CSV = ROOT_DIR / "config" / "universe_spike.csv"
M0_SPIKE_RESULT_MD = ROOT_DIR / "docs" / "m0-spike-result.md"
GOLDEN_SUMMARY_JSON = ROOT_DIR / "tests" / "fixtures" / "m0_golden_summary.json"
SYNTHETIC_RECORDS_JSON = ROOT_DIR / "tests" / "fixtures" / "synthetic_50_ticker_records.json"
SYNTHETIC_SUMMARY_JSON = ROOT_DIR / "tests" / "fixtures" / "synthetic_50_ticker_summary.json"


def generate_m0_golden_summary_from_artifact() -> None:
    """Read real M0 spike artifact markdown and generate authoritative M0 Golden Summary json."""
    assert M0_SPIKE_RESULT_MD.exists(), f"M0 spike artifact missing at {M0_SPIKE_RESULT_MD}"
    content = M0_SPIKE_RESULT_MD.read_text(encoding="utf-8")

    # Parse rows from markdown table
    price_match = re.search(r"\|\s*price\s*\|\s*(\d+)\s*\|", content)
    inst_match = re.search(r"\|\s*institutional\s*\|\s*(\d+)\s*\|", content)
    margin_match = re.search(r"\|\s*margin\s*\|\s*(\d+)\s*\|", content)
    ticker_match = re.search(r"-\s*股票數：(\d+)", content)
    no_trade_match = re.search(r"-\s*無成交／停牌語意列（價格轉為 null）：(\d+)", content)
    join_match = re.search(r"（(\d+\.\d+)%）", content)
    date_match = re.search(r"-\s*請求區間：(\d{4}-\d{2}-\d{2})\s*～\s*(\d{4}-\d{2}-\d{2})", content)

    assert price_match, "Failed to parse price rows from M0 spike result"
    assert inst_match, "Failed to parse institutional rows from M0 spike result"
    assert margin_match, "Failed to parse margin rows from M0 spike result"
    assert ticker_match, "Failed to parse ticker count from M0 spike result"
    assert no_trade_match, "Failed to parse no_trade count from M0 spike result"
    assert join_match, "Failed to parse join ratio from M0 spike result"
    assert date_match, "Failed to parse date range from M0 spike result"

    golden_summary = {
        "version": "schema-v0.1",
        "generation_command": "uv run python scripts/generate_m0_golden_fixture.py",
        "source_artifact": "docs/m0-spike-result.md",
        "node_spike_commit": "5fb2b8a38cfb6ebb76d444813f2ef843ac6b7d74",
        "date_range": f"{date_match.group(1)} to {date_match.group(2)}",
        "ticker_count": int(ticker_match.group(1)),
        "total_price_records": int(price_match.group(1)),
        "total_institutional_records": int(inst_match.group(1)),
        "total_margin_records": int(margin_match.group(1)),
        "primary_key_duplicates": 0,
        "three_table_join_ratio": float(join_match.group(1)) / 100.0,
        "no_trade_records_count": int(no_trade_match.group(1)),
        "twse_sample_ticker": "2330",
        "tpex_sample_ticker": "8069",
    }

    json_content = json.dumps(golden_summary, indent=2, ensure_ascii=False) + "\n"
    GOLDEN_SUMMARY_JSON.write_text(json_content, encoding="utf-8")
    print(f"Generated {GOLDEN_SUMMARY_JSON} from real M0 artifact {M0_SPIKE_RESULT_MD}")


def generate_synthetic_fixtures() -> None:
    tickers = []
    tpex_tickers = set()
    with open(UNIVERSE_CSV, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            s_id = row["stock_id"]
            tickers.append(s_id)
            if row["market"] == "TPEx":
                tpex_tickers.add(s_id)

    assert len(tickers) == 50, f"Expected 50 tickers, got {len(tickers)}"
    assert len(set(tickers)) == 50, f"Expected 50 unique tickers, got {len(set(tickers))}"

    price_data = []
    institutional_data = {}
    margin_data = {}

    d1 = "2026-09-25"
    d2 = "2026-09-24"
    no_trade_set = {"8069", "8299", "6690"}  # Exactly 3 tickers on d2 are no-trade

    for idx, s_id in enumerate(tickers):
        close_p1 = round(100.0 + idx * 2.5, 2)
        price_data.append(
            {
                "stock_id": s_id,
                "date": d1,
                "open": round(close_p1 - 1.0, 2),
                "max": round(close_p1 + 2.0, 2),
                "min": round(close_p1 - 2.0, 2),
                "close": close_p1,
                "spread": 1.5,
                "Trading_Volume": 100000 + idx * 5000,
                "Trading_money": int((100000 + idx * 5000) * close_p1),
                "Trading_turnover": 500 + idx * 10,
            }
        )
        institutional_data[s_id] = [
            {
                "date": d1,
                "stock_id": s_id,
                "name": "Foreign_Investor",
                "buy": 10000 + idx * 100,
                "sell": 4000 + idx * 50,
            },
            {
                "date": d1,
                "stock_id": s_id,
                "name": "Investment_Trust",
                "buy": 2000 + idx * 50,
                "sell": 500 + idx * 10,
            },
            {
                "date": d1,
                "stock_id": s_id,
                "name": "Dealer_Self",
                "buy": 1000 + idx * 20,
                "sell": 300 + idx * 5,
            },
        ]
        margin_data[s_id] = [
            {
                "date": d1,
                "stock_id": s_id,
                "MarginPurchaseBuy": 1000 + idx * 10,
                "MarginPurchaseSell": 300 + idx * 5,
                "MarginPurchaseCashRedemption": 10,
                "MarginPurchaseTodayBalance": 15000 + idx * 100,
                "MarginPurchaseLimit": 250000,
                "ShortSaleBuy": 150 + idx * 2,
                "ShortSaleSell": 300 + idx * 4,
                "ShortSaleCashRedemption": 5,
                "ShortSaleTodayBalance": 3200 + idx * 20,
                "ShortSaleLimit": 250000,
            }
        ]

        is_no_trade = s_id in no_trade_set
        close_p2 = None if is_no_trade else round(99.0 + idx * 2.5, 2)
        price_data.append(
            {
                "stock_id": s_id,
                "date": d2,
                "open": None if is_no_trade else round((close_p2 or 0) - 1.0, 2),
                "max": None if is_no_trade else round((close_p2 or 0) + 2.0, 2),
                "min": None if is_no_trade else round((close_p2 or 0) - 2.0, 2),
                "close": close_p2,
                "spread": None if is_no_trade else 1.0,
                "Trading_Volume": 0 if is_no_trade else (90000 + idx * 5000),
                "Trading_money": 0 if is_no_trade else int((90000 + idx * 5000) * (close_p2 or 0)),
                "Trading_turnover": 0 if is_no_trade else (450 + idx * 10),
            }
        )

        if not is_no_trade:
            institutional_data[s_id].append(
                {
                    "date": d2,
                    "stock_id": s_id,
                    "name": "Foreign_Investor",
                    "buy": 8000 + idx * 100,
                    "sell": 3000 + idx * 50,
                }
            )
            margin_data[s_id].append(
                {
                    "date": d2,
                    "stock_id": s_id,
                    "MarginPurchaseBuy": 800 + idx * 10,
                    "MarginPurchaseSell": 200 + idx * 5,
                    "MarginPurchaseCashRedemption": 5,
                    "MarginPurchaseTodayBalance": 14500 + idx * 100,
                    "MarginPurchaseLimit": 250000,
                    "ShortSaleBuy": 100 + idx * 2,
                    "ShortSaleSell": 250 + idx * 4,
                    "ShortSaleCashRedemption": 2,
                    "ShortSaleTodayBalance": 3100 + idx * 20,
                    "ShortSaleLimit": 250000,
                }
            )

    records_payload = {
        "dataset": "synthetic_50_ticker_sample_v0.1",
        "tickers": tickers,
        "price_data": price_data,
        "institutional_data": institutional_data,
        "margin_data": margin_data,
    }

    records_json_str = json.dumps(records_payload, indent=2, ensure_ascii=False) + "\n"
    records_bytes = records_json_str.encode("utf-8")
    SYNTHETIC_RECORDS_JSON.write_bytes(records_bytes)

    source_sha256 = hashlib.sha256(records_bytes).hexdigest()

    summary_payload = {
        "version": "schema-v0.1",
        "type": "synthetic_sample",
        "generation_command": "uv run python scripts/generate_m0_golden_fixture.py",
        "source_file": "tests/fixtures/synthetic_50_ticker_records.json",
        "source_file_sha256": source_sha256,
        "ticker_count": 50,
        "total_price_records": len(price_data),
        "total_institutional_records": 97,
        "total_margin_records": 97,
        "primary_key_duplicates": 0,
        "three_table_join_ratio": 1.0,
        "no_trade_records_count": 3,
    }

    summary_json_str = json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n"
    SYNTHETIC_SUMMARY_JSON.write_bytes(summary_json_str.encode("utf-8"))

    print(f"Generated {SYNTHETIC_RECORDS_JSON} and {SYNTHETIC_SUMMARY_JSON}")
    print(f"Synthetic SHA256: {source_sha256}")


if __name__ == "__main__":
    generate_m0_golden_summary_from_artifact()
    generate_synthetic_fixtures()

