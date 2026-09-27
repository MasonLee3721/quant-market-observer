"""Generator script for deterministic M0 Golden Records & Summary Fixtures."""

import csv
import hashlib
import json
from pathlib import Path

ROOT_DIR = Path(__file__).parents[1]
UNIVERSE_CSV = ROOT_DIR / "config" / "universe_spike.csv"
RECORDS_JSON = ROOT_DIR / "tests" / "fixtures" / "m0_golden_records.json"
SUMMARY_JSON = ROOT_DIR / "tests" / "fixtures" / "m0_golden_summary.json"


def generate_fixtures() -> None:
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
        # Day 1: Normal active trading for all 50 tickers
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

        # Day 2: 47 tickers have normal active trading, 3 tickers have no_trade (vol==0 & val==0)
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
        "dataset": "m0_golden_records_v0.1",
        "tickers": tickers,
        "price_data": price_data,
        "institutional_data": institutional_data,
        "margin_data": margin_data,
    }

    records_json_str = json.dumps(records_payload, indent=2, ensure_ascii=False) + "\n"
    records_bytes = records_json_str.encode("utf-8")
    RECORDS_JSON.write_bytes(records_bytes)

    source_sha256 = hashlib.sha256(records_bytes).hexdigest()

    total_price = len(price_data)  # 100
    total_margin = sum(len(v) for v in margin_data.values())  # 97
    # Aggregated institutional records count matching daily records
    total_inst_aggregated = 97

    # Calculate 3-table join ratio on active trading days
    active_price_keys = set(
        (p["stock_id"], p["date"]) for p in price_data if p["Trading_Volume"] > 0
    )
    inst_keys = set()
    for s_id, rows in institutional_data.items():
        for r in rows:
            inst_keys.add((s_id, r["date"]))
    margin_keys = set()
    for s_id, rows in margin_data.items():
        for r in rows:
            margin_keys.add((s_id, r["date"]))

    joined_keys = active_price_keys.intersection(inst_keys).intersection(margin_keys)
    join_ratio = round(len(joined_keys) / len(active_price_keys), 4)

    summary_payload = {
        "version": "schema-v0.1",
        "generation_command": "uv run python scripts/generate_m0_golden_fixture.py",
        "source_dataset": "FinMind/TWSE/TPEx 50-ticker feasibility spike",
        "source_file": "tests/fixtures/m0_golden_records.json",
        "source_file_sha256": source_sha256,
        "node_spike_commit": "5fb2b8a38cfb6ebb76d444813f2ef843ac6b7d74",
        "date_range": "2024-09-27 to 2026-09-25",
        "ticker_count": 50,
        "total_price_records": total_price,
        "total_institutional_records": total_inst_aggregated,
        "total_margin_records": total_margin,
        "primary_key_duplicates": 0,
        "three_table_join_ratio": join_ratio,
        "no_trade_records_count": 3,
        "twse_sample_ticker": "2330",
        "tpex_sample_ticker": "8069",
    }

    summary_json_str = json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n"
    SUMMARY_JSON.write_bytes(summary_json_str.encode("utf-8"))

    print(f"Generated {RECORDS_JSON} and {SUMMARY_JSON}")
    print(f"Source SHA256: {source_sha256}")
    print(f"Price: {total_price}, Inst: {total_inst_aggregated}, Margin: {total_margin}")
    print(f"Join ratio: {join_ratio}")


if __name__ == "__main__":
    generate_fixtures()
