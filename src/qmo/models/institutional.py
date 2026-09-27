"""Institutional Flow Data Model adhering to M0 Data Contract Schema."""

import re
from typing import List

from pydantic import BaseModel, Field, field_validator


class InstitutionalFlow(BaseModel):
    """Normalized Institutional Investor Buy/Sell Flow Record."""

    trade_date: str  # YYYY-MM-DD
    stock_id: str
    market: str = "TWSE"
    foreign_buy: int = 0
    foreign_sell: int = 0
    foreign_net: int = 0
    investment_trust_buy: int = 0
    investment_trust_sell: int = 0
    investment_trust_net: int = 0
    dealer_buy: int = 0
    dealer_sell: int = 0
    dealer_net: int = 0
    total_net: int = 0
    source: str = "finmind"
    retrieved_at: str = ""
    schema_version: str = "v0.1"
    quality_flags: List[str] = Field(default_factory=list)

    @field_validator("trade_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"trade_date must be in ISO format YYYY-MM-DD, got: {v}")
        return v
