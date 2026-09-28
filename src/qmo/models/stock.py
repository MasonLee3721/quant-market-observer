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
    try:
        data_obj = json.loads(payload_json)
        rows = data_obj.get("data", []) if isinstance(data_obj, dict) else []
        for r in rows:
            sid = str(r.get("stock_id", ""))
            if not sid:
                continue
            mkt = "TPEx" if "櫃" in str(r.get("type", "")) else "TWSE"
            registry[sid] = StockMaster(
                symbol=sid,
                name=str(r.get("stock_name", sid)),
                market=mkt,
                industry=r.get("industry_category"),
                is_active=True,
            )
    except Exception:
        pass
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
