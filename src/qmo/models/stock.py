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
    """Parse raw TaiwanStockInfo JSON payload into StockMaster registry dictionary."""
    import json

    registry: Dict[str, StockMaster] = {}
    data_obj = json.loads(payload_json)
    if not isinstance(data_obj, dict) or not isinstance(data_obj.get("data"), list):
        raise ValueError("TaiwanStockInfo payload must contain a data list")
    for row in data_obj["data"]:
        if not isinstance(row, dict):
            raise ValueError("TaiwanStockInfo data rows must be objects")
        sid = str(row.get("stock_id", "")).strip()
        stock_type = str(row.get("type", "")).strip()
        if not sid:
            continue
        if "上櫃" in stock_type or "櫃" in stock_type:
            market = "TPEx"
        elif "上市" in stock_type:
            market = "TWSE"
        else:
            continue
        registry[sid] = StockMaster(
            symbol=sid,
            name=str(row.get("stock_name", sid)),
            market=market,
            industry=row.get("industry_category"),
            is_active=True,
        )
    if not registry:
        raise ValueError("TaiwanStockInfo contained no listed or OTC stocks")
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
