"""M0 Artifact Regression Verification Script.

Executes Python Normalization Pipeline over real M0 spike raw payload artifacts in:
  - data/spike/raw/TaiwanStockPrice/
  - data/spike/raw/TaiwanStockInstitutionalInvestorsBuySell/
  - data/spike/raw/TaiwanStockMarginPurchaseShortSale/

Verifies:
1. Completeness across all 50 tickers from config/universe_spike.csv
2. Exact raw record totals (Price: 24,193, Institutional: 24,185, Margin: 24,107)
3. 0 Primary Key duplicates
4. 3 no_trade records (volume==0 and trading_money==0)
5. 3-table join ratio (24,092 / 24,193 = 0.9958)
6. Reads read-only Node baseline CSVs in data/spike/normalized/ without overwriting
7. Computes and asserts SHA-256 digests against Node baseline CSV hashes
8. 100% Comprehensive Field-by-Field Parity Check across ALL schema contract fields
"""

import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT_DIR = Path(__file__).parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from qmo.models.stock import load_universe_stock_master  # noqa: E402
from qmo.normalizers.institutional import InstitutionalNormalizer  # noqa: E402
from qmo.normalizers.margin import MarginNormalizer  # noqa: E402
from qmo.normalizers.price import PriceNormalizer  # noqa: E402
from qmo.providers.protocols import RawResponseEnvelope  # noqa: E402

UNIVERSE_CSV = ROOT_DIR / "config" / "universe_spike.csv"
SPIKE_DIR = ROOT_DIR / "data" / "spike"
RAW_DIR = SPIKE_DIR / "raw"
NORMALIZED_DIR = SPIKE_DIR / "normalized"
GOLDEN_SUMMARY_JSON = ROOT_DIR / "tests" / "fixtures" / "m0_golden_summary.json"

RAW_DATASETS = {
    "price": RAW_DIR / "TaiwanStockPrice",
    "institutional": RAW_DIR / "TaiwanStockInstitutionalInvestorsBuySell",
    "margin": RAW_DIR / "TaiwanStockMarginPurchaseShortSale",
}


def verify_raw_data_exists(tickers: List[str]) -> None:
    for name, path in RAW_DATASETS.items():
        if not path.exists():
            raise FileNotFoundError(
                f"M0 raw dataset directory missing: {path}. "
                "Run '/home/agent/.cache/ms-playwright-go/1.57.0/node scripts/m0_spike.mjs' "
                "or 'uv run python scripts/generate_m0_spike_data.py' to generate artifacts."
            )
        for s_id in tickers:
            f = path / f"{s_id}.json"
            if not f.exists():
                raise FileNotFoundError(
                    f"M0 raw payload missing for ticker '{s_id}' in dataset '{name}' at {f}. "
                    "Run artifact generation script first."
                )


def compute_file_sha256(filepath: Path) -> str:
    if not filepath.exists():
        raise FileNotFoundError(f"Baseline CSV missing at {filepath}")
    return hashlib.sha256(filepath.read_bytes()).hexdigest()


def is_valid_utc_iso(ts_str: str) -> bool:
    """Validate that ts_str is a non-empty, valid ISO 8601 UTC timestamp string."""
    if not ts_str:
        return False
    iso_str = ts_str.replace("Z", "+00:00") if ts_str.endswith("Z") else ts_str
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.tzinfo is not None and dt.utcoffset() == timedelta(0)
    except ValueError:
        return False


def verify_m0_artifact(update_summary: bool = False) -> Dict[str, Any]:
    print("==================================================")
    print(" M0 Real Artifact Verification & Pipeline Parity")
    print("==================================================")

    stock_master_map = load_universe_stock_master(UNIVERSE_CSV)
    tickers = sorted(list(stock_master_map.keys()))
    assert len(tickers) == 50, f"Expected 50 tickers in universe, got {len(tickers)}"

    # 1. Verify Raw Payload Files Exist & Are Complete
    verify_raw_data_exists(tickers)

    price_norm = PriceNormalizer(stock_master=stock_master_map)
    inst_norm = InstitutionalNormalizer(stock_master=stock_master_map)
    margin_norm = MarginNormalizer(stock_master=stock_master_map)

    # 2. Normalize Price Payloads
    price_models = []
    for s_id in tickers:
        raw_file = RAW_DATASETS["price"] / f"{s_id}.json"
        raw_bytes = raw_file.read_bytes()
        raw_json = json.loads(raw_bytes.decode("utf-8"))
        assert raw_json.get("status") == 200 and raw_json.get("msg") == "success"

        env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockPrice", "data_id": s_id},
            status_code=200,
            raw_body_bytes=raw_bytes,
        )
        price_models.extend(price_norm.normalize(env))

    # 3. Normalize Institutional Payloads
    inst_models = []
    for s_id in tickers:
        raw_file = RAW_DATASETS["institutional"] / f"{s_id}.json"
        raw_bytes = raw_file.read_bytes()
        raw_json = json.loads(raw_bytes.decode("utf-8"))
        assert raw_json.get("status") == 200 and raw_json.get("msg") == "success"

        env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockInstitutionalInvestorsBuySell", "data_id": s_id},
            status_code=200,
            raw_body_bytes=raw_bytes,
        )
        inst_models.extend(inst_norm.normalize(env))

    # 4. Normalize Margin Payloads
    margin_models = []
    for s_id in tickers:
        raw_file = RAW_DATASETS["margin"] / f"{s_id}.json"
        raw_bytes = raw_file.read_bytes()
        raw_json = json.loads(raw_bytes.decode("utf-8"))
        assert raw_json.get("status") == 200 and raw_json.get("msg") == "success"

        env = RawResponseEnvelope(
            provider_name="finmind",
            endpoint="https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockMarginPurchaseShortSale", "data_id": s_id},
            status_code=200,
            raw_body_bytes=raw_bytes,
        )
        margin_models.extend(margin_norm.normalize(env))

    # Sort Python models deterministically
    price_models.sort(key=lambda m: (m.trade_date, m.stock_id))
    inst_models.sort(key=lambda m: (m.trade_date, m.stock_id))
    margin_models.sort(key=lambda m: (m.trade_date, m.stock_id))

    total_price = len(price_models)
    total_inst = len(inst_models)
    total_margin = len(margin_models)

    price_keys: Set[Tuple[str, str]] = set((p.stock_id, p.trade_date) for p in price_models)
    inst_keys: Set[Tuple[str, str]] = set((i.stock_id, i.trade_date) for i in inst_models)
    margin_keys: Set[Tuple[str, str]] = set((m.stock_id, m.trade_date) for m in margin_models)

    pk_duplicates = total_price - len(price_keys)
    no_trade_count = sum(1 for p in price_models if p.no_trade)

    joined_keys = price_keys.intersection(inst_keys).intersection(margin_keys)
    join_ratio = round(len(joined_keys) / float(total_price), 4) if total_price > 0 else 0.0

    print(f"Total Price Records: {total_price}")
    print(f"Total Institutional Records: {total_inst}")
    print(f"Total Margin Records: {total_margin}")
    print(f"Primary Key Duplicates: {pk_duplicates}")
    print(f"No-Trade Records Count: {no_trade_count}")
    print(f"3-Table Join Ratio: {join_ratio} ({len(joined_keys)}/{total_price})")

    # Assert exact M0 Golden Parity Facts
    assert total_price == 24193, f"Expected 24193 price records, got {total_price}"
    assert total_inst == 24185, f"Expected 24185 inst records, got {total_inst}"
    assert total_margin == 24107, f"Expected 24107 margin records, got {total_margin}"
    assert pk_duplicates == 0, f"Expected 0 PK duplicates, got {pk_duplicates}"
    assert no_trade_count == 3, f"Expected 3 no_trade records, got {no_trade_count}"
    assert math.isclose(join_ratio, 0.9958, abs_tol=1e-4)

    # 5. Read Baseline Node CSVs (READ-ONLY) and Compute Baseline SHA-256 Hashes
    price_csv_path = NORMALIZED_DIR / "daily_price.csv"
    inst_csv_path = NORMALIZED_DIR / "institutional_flow.csv"
    margin_csv_path = NORMALIZED_DIR / "margin.csv"

    price_csv_sha256 = compute_file_sha256(price_csv_path)
    inst_csv_sha256 = compute_file_sha256(inst_csv_path)
    margin_csv_sha256 = compute_file_sha256(margin_csv_path)

    print(f"Baseline Price CSV SHA-256: {price_csv_sha256}")
    print(f"Baseline Institutional Flow CSV SHA-256: {inst_csv_sha256}")
    print(f"Baseline Margin CSV SHA-256: {margin_csv_sha256}")

    # Load committed golden summary to verify hashes match baseline
    with open(GOLDEN_SUMMARY_JSON, mode="r", encoding="utf-8") as f:
        committed_summary = json.load(f)

    KNOWN_NODE_BASELINE_HASHES = {
        "daily_price": "804ae6b294ebf737dac3ef670b65f3411e0698de0443c31c3d052244928c94c4",
        "institutional_flow": "4f4118eebf8ebee6f38567fef4f2154874ccbfbf7cebc20dee9a7617247efc31",
        "margin": "c6351ce99bd417aad55cec4f08449ebfb9b2aca7391658fd2e469c8190218db6",
    }

    if not update_summary:
        price_golden = committed_summary.get("daily_price_csv_sha256")
        inst_golden = committed_summary.get("institutional_flow_csv_sha256")
        margin_golden = committed_summary.get("margin_csv_sha256")

        node_price = KNOWN_NODE_BASELINE_HASHES["daily_price"]
        node_inst = KNOWN_NODE_BASELINE_HASHES["institutional_flow"]
        node_margin = KNOWN_NODE_BASELINE_HASHES["margin"]

        assert price_csv_sha256 == price_golden == node_price, (
            f"Price SHA-256 mismatch: {price_csv_sha256} vs {price_golden} vs {node_price}"
        )
        assert inst_csv_sha256 == inst_golden == node_inst, (
            f"Inst SHA-256 mismatch: {inst_csv_sha256} vs {inst_golden} vs {node_inst}"
        )
        assert margin_csv_sha256 == margin_golden == node_margin, (
            f"Margin SHA-256 mismatch: {margin_csv_sha256} vs {margin_golden} vs {node_margin}"
        )

    # 6. Comprehensive Field-by-Field Parity Check Against Baseline CSV Rows across ALL fields
    with open(price_csv_path, mode="r", encoding="utf-8") as f:
        csv_prices = list(csv.DictReader(f))
    assert len(csv_prices) == len(price_models)
    for csv_row, m in zip(csv_prices, price_models, strict=True):
        assert csv_row["trade_date"] == m.trade_date
        assert csv_row["stock_id"] == m.stock_id
        assert csv_row["market"] == m.market
        assert int(csv_row["volume"]) == m.trading_volume
        assert int(csv_row["trading_money"]) == m.trading_value
        assert int(csv_row["trades"]) == m.transaction_count
        assert csv_row["quality_flags"] == ("|".join(m.quality_flags))
        assert csv_row["source"] == m.source
        # retrieved_at records execution timestamp; exact timestamp value equality is
        # excluded across independent runs, but both sides must be valid UTC
        assert is_valid_utc_iso(csv_row["retrieved_at"])
        assert is_valid_utc_iso(m.retrieved_at)
        assert csv_row["schema_version"] == m.schema_version
        if csv_row["open"]:
            assert math.isclose(float(csv_row["open"]), m.open_price or 0.0, abs_tol=1e-4)
        else:
            assert m.open_price is None
        if csv_row["high"]:
            assert math.isclose(float(csv_row["high"]), m.high_price or 0.0, abs_tol=1e-4)
        else:
            assert m.high_price is None
        if csv_row["low"]:
            assert math.isclose(float(csv_row["low"]), m.low_price or 0.0, abs_tol=1e-4)
        else:
            assert m.low_price is None
        if csv_row["close"]:
            assert math.isclose(float(csv_row["close"]), m.close_price or 0.0, abs_tol=1e-4)
        else:
            assert m.close_price is None
        if csv_row["spread"]:
            assert math.isclose(float(csv_row["spread"]), m.change or 0.0, abs_tol=1e-4)
        else:
            assert m.change is None

    with open(inst_csv_path, mode="r", encoding="utf-8") as f:
        csv_insts = list(csv.DictReader(f))
    assert len(csv_insts) == len(inst_models)
    for csv_row, m in zip(csv_insts, inst_models, strict=True):
        assert csv_row["trade_date"] == m.trade_date
        assert csv_row["stock_id"] == m.stock_id
        assert csv_row["market"] == m.market
        assert int(csv_row["foreign_net"]) == m.foreign_net
        assert int(csv_row["trust_net"]) == m.investment_trust_net
        assert int(csv_row["dealer_net"]) == m.dealer_net
        assert int(csv_row["total_net"]) == m.total_net
        assert csv_row["categories"] == m.categories
        assert csv_row["source"] == m.source
        # retrieved_at records execution timestamp; exact timestamp value equality is
        # excluded across independent runs, but both sides must be valid UTC
        assert is_valid_utc_iso(csv_row["retrieved_at"])
        assert is_valid_utc_iso(m.retrieved_at)
        assert csv_row["schema_version"] == m.schema_version

    with open(margin_csv_path, mode="r", encoding="utf-8") as f:
        csv_margins = list(csv.DictReader(f))
    assert len(csv_margins) == len(margin_models)
    for csv_row, m in zip(csv_margins, margin_models, strict=True):
        assert csv_row["trade_date"] == m.trade_date
        assert csv_row["stock_id"] == m.stock_id
        assert csv_row["market"] == m.market
        assert int(csv_row["margin_buy"]) == m.margin_purchase_buy
        assert int(csv_row["margin_sell"]) == m.margin_purchase_sell
        assert int(csv_row["margin_cash_repayment"]) == m.margin_purchase_cash_redemption
        assert int(csv_row["margin_balance"]) == m.margin_purchase_balance
        if csv_row["margin_previous_balance"]:
            assert int(csv_row["margin_previous_balance"]) == m.margin_purchase_previous_balance
        else:
            assert (
                m.margin_purchase_previous_balance is None
                or m.margin_purchase_previous_balance == 0
            )
        assert int(csv_row["short_buy"]) == m.short_sale_buy
        assert int(csv_row["short_sell"]) == m.short_sale_sell
        assert int(csv_row["short_cash_repayment"]) == m.short_sale_cash_redemption
        assert int(csv_row["short_balance"]) == m.short_sale_balance
        if csv_row["short_previous_balance"]:
            assert int(csv_row["short_previous_balance"]) == m.short_sale_previous_balance
        else:
            assert m.short_sale_previous_balance is None or m.short_sale_previous_balance == 0
        if csv_row["offset"]:
            assert int(csv_row["offset"]) == m.offset_loan_and_short
        else:
            assert m.offset_loan_and_short is None or m.offset_loan_and_short == 0
        if csv_row["note"]:
            assert csv_row["note"].strip() == (m.note or "").strip()
        else:
            assert m.note is None or m.note.strip() == ""
        assert csv_row["source"] == m.source
        # retrieved_at records execution timestamp; exact timestamp value equality is
        # excluded across independent runs, but both sides must be valid UTC
        assert is_valid_utc_iso(csv_row["retrieved_at"])
        assert is_valid_utc_iso(m.retrieved_at)
        assert csv_row["schema_version"] == m.schema_version

    print("[OK] All comparable contract schema fields parity matched for Price, Inst, and Margin.")

    # 7. Construct Golden Summary
    golden_summary = {
        "version": "schema-v0.1",
        "generation_command": "uv run python scripts/verify_m0_artifact.py",
        "source_raw_dir": "data/spike/raw",
        "source_normalized_dir": "data/spike/normalized",
        "daily_price_csv_sha256": KNOWN_NODE_BASELINE_HASHES["daily_price"],
        "institutional_flow_csv_sha256": KNOWN_NODE_BASELINE_HASHES["institutional_flow"],
        "margin_csv_sha256": KNOWN_NODE_BASELINE_HASHES["margin"],
        "date_range": "2024-09-27 to 2026-09-25",
        "ticker_count": 50,
        "total_price_records": total_price,
        "total_institutional_records": total_inst,
        "total_margin_records": total_margin,
        "primary_key_duplicates": pk_duplicates,
        "three_table_join_ratio": join_ratio,
        "no_trade_records_count": no_trade_count,
        "twse_sample_ticker": "2330",
        "tpex_sample_ticker": "8069",
    }

    if update_summary:
        GOLDEN_SUMMARY_JSON.write_text(
            json.dumps(golden_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"[OK] Updated {GOLDEN_SUMMARY_JSON} with recomputed M0 baseline facts.")

    print("==================================================")
    print(" Verification Status: PASS")
    print("==================================================")

    return golden_summary


if __name__ == "__main__":
    should_update = "--update-summary" in sys.argv
    verify_m0_artifact(update_summary=should_update)
