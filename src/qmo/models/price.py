"""Daily Price Data Model with Strict Null / No-Trade Semantics."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class DailyPrice(BaseModel):
    """Normalized Daily Stock Price Record."""

    symbol: str
    date: str  # YYYY-MM-DD
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
    schema_version: str = "1.0"

    @model_validator(mode="after")
    def validate_no_trade_semantics(self) -> "DailyPrice":
        # If trading volume is 0 or price is None, no_trade must be True
        if self.trading_volume == 0 or self.close_price is None:
            self.no_trade = True
            self.open_price = None
            self.high_price = None
            self.low_price = None
            self.close_price = None
        return self
