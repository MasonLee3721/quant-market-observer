"""Margin Trading Data Model adhering to M0 Data Contract Schema."""

from datetime import datetime
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
            try:
                dt = datetime.fromisoformat(v)
                if dt.tzinfo is None:
                    raise ValueError(
                        f"retrieved_at must be UTC timezone-aware ISO string, got: {v}"
                    )
            except ValueError as e:
                raise ValueError(f"retrieved_at must be valid UTC ISO datetime, got: {v}") from e
        return v
