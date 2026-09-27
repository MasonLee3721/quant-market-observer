"""Institutional Flow Data Model adhering to M0 Data Contract Schema."""

from datetime import datetime
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
    schema_version: str = "schema-v0.1"
    quality_flags: List[str] = Field(default_factory=list)

    @field_validator("trade_date")
    @classmethod
    def validate_real_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"trade_date must be a valid ISO date YYYY-MM-DD, got: {v}") from e
        return v
