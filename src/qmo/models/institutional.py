"""Institutional Flow Data Model adhering to M0 Data Contract Schema."""

from datetime import datetime, timedelta
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
    categories: str = ""
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

    @field_validator("retrieved_at")
    @classmethod
    def validate_utc_iso_datetime(cls, v: str) -> str:
        if v:
            iso_str = v.replace("Z", "+00:00") if v.endswith("Z") else v
            try:
                dt = datetime.fromisoformat(iso_str)
            except ValueError as e:
                raise ValueError(f"retrieved_at must be valid UTC ISO datetime, got: {v}") from e

            if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
                raise ValueError(f"retrieved_at must be UTC timezone-aware (+00:00 or Z), got: {v}")
        return v
