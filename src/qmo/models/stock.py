"""Stock Master Metadata Data Model."""

from typing import Optional

from pydantic import BaseModel


class StockMaster(BaseModel):
    """Stock Metadata Master Record."""

    symbol: str
    name: str
    market: str  # TWSE / TPEx
    industry: Optional[str] = None
    is_active: bool = True
