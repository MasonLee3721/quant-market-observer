"""Margin Trading Data Model adhering to M0 Data Contract Schema."""

from datetime import datetime, timedelta
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
    margin_purchase_previous_balance: int = 0
    margin_purchase_quota: int = 0
    short_sale_buy: int = 0
    short_sale_sell: int = 0
    short_sale_cash_redemption: int = 0
    short_sale_balance: int = 0
    short_sale_previous_balance: int = 0
    short_sale_quota: int = 0
    offset_loan_and_short: int = 0
    note: str = ""
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
