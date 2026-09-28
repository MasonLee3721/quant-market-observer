"""Stock Master Metadata Model and Universe Registry Loader."""

import csv
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel


class StockMaster(BaseModel):
    """Stock Metadata Master Record."""

    symbol: str
    name: str
    market: str  # TWSE / TPEx
    industry: Optional[str] = None
    is_active: bool = True


def parse_stock_info_payload(payload_json: str) -> Dict[str, StockMaster]:
    """Parse the latest active TWSE/TPEx common-stock universe.

    FinMind TaiwanStockInfo contains historical snapshots and non-equity
    instruments. Production ingestion deliberately excludes ETFs, ETNs,
    indices, depositary receipts, warrants, and non-four-digit symbols.
    """
    import json
    import re

    data_obj = json.loads(payload_json)
    if not isinstance(data_obj, dict) or not isinstance(data_obj.get("data"), list):
        raise ValueError("TaiwanStockInfo payload must contain a data list")
    rows = data_obj["data"]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("TaiwanStockInfo data rows must be objects")

    iso_date = re.compile(r"\d{4}-\d{2}-\d{2}")
    market_types = {"twse", "tpex", "上市", "上櫃"}
    valid_dates = [
        str(row.get("date"))
        for row in rows
        if str(row.get("type", "")).strip().casefold() in market_types
        and iso_date.fullmatch(str(row.get("date")))
    ]
    if not valid_dates:
        raise ValueError("TaiwanStockInfo contained no valid snapshot dates")
    latest_date = max(valid_dates)
    excluded_categories = (
        "etf",
        "etn",
        "index",
        "指數",
        "存託憑證",
        "受益證券",
        "所有證券",
        "大盤",
    )

    registry: Dict[str, StockMaster] = {}
    for row in rows:
        if str(row.get("date")) != latest_date:
            continue
        sid = str(row.get("stock_id", "")).strip()
        stock_type = str(row.get("type", "")).strip().casefold()
        industry = str(row.get("industry_category", "")).strip()
        if not re.fullmatch(r"\d{4}", sid) or sid.startswith("00"):
            continue
        if any(token in industry.casefold() for token in excluded_categories):
            continue
        if stock_type in {"tpex", "上櫃"}:
            market = "TPEx"
        elif stock_type in {"twse", "上市"}:
            market = "TWSE"
        else:
            continue
        registry[sid] = StockMaster(
            symbol=sid,
            name=str(row.get("stock_name", sid)),
            market=market,
            industry=industry or None,
            is_active=True,
        )
    if not registry:
        raise ValueError("TaiwanStockInfo contained no active listed or OTC common stocks")
    return registry


def load_universe_stock_master(csv_path: Optional[Path] = None) -> Dict[str, StockMaster]:
    """Load stock master universe mapping from CSV file."""
    if csv_path is None:
        csv_path = Path(__file__).parents[3] / "config" / "universe_spike.csv"

    registry: Dict[str, StockMaster] = {}
    if not csv_path.exists():
        return registry

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row["stock_id"]
            registry[sid] = StockMaster(
                symbol=sid,
                name=row.get("name", ""),
                market=row.get("market", "TWSE"),
                industry=row.get("subtheme"),
            )
    return registry
