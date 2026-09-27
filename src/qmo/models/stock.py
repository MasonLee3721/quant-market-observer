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
