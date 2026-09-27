"""Margin Trading Data Model."""

from pydantic import BaseModel


class Margin(BaseModel):
    """Normalized Margin Purchase and Short Sale Record."""

    symbol: str
    date: str  # YYYY-MM-DD
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
    schema_version: str = "1.0"
