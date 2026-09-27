"""Margin Trading Data Model adhering to M0 Data Contract Schema."""

import re
from typing import List

from pydantic import BaseModel, Field, field_validator


class Margin(BaseModel):
    """Normalized Margin Purchase and Short Sale Record."""

    trade_date: str  # YYYY-MM-DD
    stock_id: str
    market: str = "TWSE"
    margin_purchase_buy: int = 0
    margin_purchase_sell: int = 0
    margin_purchase_cash_redemption: int = 0
    margin_purchase_balance: int = 0
    margin_purchase_quota: int = 0
    short_sale_buy: int = 0
    short_sale_sell: int = 0
    short_sale_cash_redemption: int = 0
    short_sale_balance: int = 0
    short_sale_quota: int = 0
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
