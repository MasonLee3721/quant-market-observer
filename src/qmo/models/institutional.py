"""Institutional Flow Data Model."""

from pydantic import BaseModel


class InstitutionalFlow(BaseModel):
    """Normalized Institutional Investor Buy/Sell Flow Record."""

    symbol: str
    date: str  # YYYY-MM-DD
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
    schema_version: str = "1.0"
