"""M0 Spike Raw and Normalized Data Generator.

Fetches raw JSON payload files from FinMind into data/spike/raw/ for all 50 tickers
in config/universe_spike.csv for 2024-09-27 to 2026-09-25.
"""

import csv
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).parents[1]
UNIVERSE_CSV = ROOT_DIR / "config" / "universe_spike.csv"
SPIKE_DIR = ROOT_DIR / "data" / "spike"
RAW_DIR = SPIKE_DIR / "raw"
NORMALIZED_DIR = SPIKE_DIR / "normalized"

DATASETS = {
    "price": "TaiwanStockPrice",
    "institutional": "TaiwanStockInstitutionalInvestorsBuySell",
    "margin": "TaiwanStockMarginPurchaseShortSale",
}


def load_universe() -> List[Dict[str, str]]:
    with open(UNIVERSE_CSV, mode="r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_raw_payloads(universe: List[Dict[str, str]], max_workers: int = 5) -> None:
    def fetch_stock(stock: Dict[str, str]) -> None:
        s_id = stock["stock_id"]
        for _, d_type in DATASETS.items():
            out_file = RAW_DIR / d_type / f"{s_id}.json"
            if not out_file.exists():
                out_file.parent.mkdir(parents=True, exist_ok=True)
                url = (
                    "https://api.finmindtrade.com/api/v4/data"
                    f"?dataset={d_type}&data_id={s_id}&start_date=2024-09-27&end_date=2026-09-25"
                )
                req = urllib.request.Request(
                    url, headers={"user-agent": "quant-market-observer-m0/0.1"}
                )
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    out_file.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(fetch_stock, universe))


def generate_spike_data() -> None:
    universe = load_universe()
    fetch_raw_payloads(universe)
    print(f"M0 spike raw payloads generated at {RAW_DIR}")


if __name__ == "__main__":
    generate_spike_data()
