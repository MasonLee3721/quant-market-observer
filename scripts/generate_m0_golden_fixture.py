"""Generator script for M0 Golden Fixtures and CI Synthetic 50-Ticker Sample Fixture."""

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.verify_m0_artifact import verify_m0_artifact  # noqa: E402

UNIVERSE_CSV = ROOT_DIR / "config" / "universe_spike.csv"
SYNTHETIC_RECORDS_JSON = ROOT_DIR / "tests" / "fixtures" / "synthetic_50_ticker_records.json"
SYNTHETIC_SUMMARY_JSON = ROOT_DIR / "tests" / "fixtures" / "synthetic_50_ticker_summary.json"


def generate_m0_golden_summary_from_artifact() -> None:
    """Run real raw JSON artifact normalizer pipeline and generate M0 Golden Summary json."""
    verify_m0_artifact()


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
