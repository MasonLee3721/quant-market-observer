"""Daily Price Data Model adhering to M0 Data Contract Schema."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class DailyPrice(BaseModel):
    """Normalized Daily Stock Price Record (M0 Data Contract Schema)."""

    trade_date: str  # YYYY-MM-DD ISO 8601
    stock_id: str
    market: str = "TWSE"  # TWSE / TPEx
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None
    change: Optional[float] = None
    trading_volume: int = Field(default=0, ge=0)
    trading_value: int = Field(default=0, ge=0)
    transaction_count: int = Field(default=0, ge=0)
    no_trade: bool = False
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

    @model_validator(mode="after")
    def validate_m0_no_trade_contract(self) -> "DailyPrice":
        # M0 Contract: no_trade is True if volume == 0 and trading_value == 0
        if self.trading_volume == 0 and self.trading_value == 0:
            self.no_trade = True
            if "no_trade" not in self.quality_flags:
                self.quality_flags.append("no_trade")
            self.open_price = None
            self.high_price = None
            self.low_price = None
            self.close_price = None
            self.change = None
        return self
