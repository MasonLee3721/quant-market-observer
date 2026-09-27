"""FinMind Data Provider Adapter."""

from typing import Optional

from qmo.providers.protocols import RawResponseEnvelope
from qmo.providers.transport import HttpTransport


class FinMindProvider:
    """Provider for FinMind historical Taiwan stock data."""

    def __init__(self, transport: Optional[HttpTransport] = None, api_token: str = "") -> None:
        self.transport = transport or HttpTransport()
        self.api_token = api_token
        self.base_url = "https://api.finmindtrade.com/api/v4/data"

    @property
    def provider_name(self) -> str:
        return "finmind"

    def fetch_daily_price(self, symbol: str, start_date: str, end_date: str) -> RawResponseEnvelope:
        params = {
            "dataset": "TaiwanStockPrice",
            "data_id": symbol,
            "start_date": start_date,
            "end_date": end_date,
        }
        if self.api_token:
            params["token"] = self.api_token

        payload = self.transport.request(self.base_url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=self.base_url,
            params=params,
            status_code=200,
            raw_payload=payload,
        )

    def fetch_institutional_flow(
        self, symbol: str, start_date: str, end_date: str
    ) -> RawResponseEnvelope:
        params = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": symbol,
            "start_date": start_date,
            "end_date": end_date,
        }
        if self.api_token:
            params["token"] = self.api_token

        payload = self.transport.request(self.base_url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=self.base_url,
            params=params,
            status_code=200,
            raw_payload=payload,
        )

    def fetch_margin(self, symbol: str, start_date: str, end_date: str) -> RawResponseEnvelope:
        params = {
            "dataset": "TaiwanStockMarginPurchaseShortSale",
            "data_id": symbol,
            "start_date": start_date,
            "end_date": end_date,
        }
        if self.api_token:
            params["token"] = self.api_token

        payload = self.transport.request(self.base_url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=self.base_url,
            params=params,
            status_code=200,
            raw_payload=payload,
        )
