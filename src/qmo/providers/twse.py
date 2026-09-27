"""TWSE (Taiwan Stock Exchange) Data Provider Adapter."""

from typing import Optional

from qmo.providers.protocols import RawResponseEnvelope
from qmo.providers.transport import HttpTransport


class TwseProvider:
    """Provider for TWSE (Listed market) official data."""

    def __init__(self, transport: Optional[HttpTransport] = None) -> None:
        self.transport = transport or HttpTransport()
        self.base_url = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"

    @property
    def provider_name(self) -> str:
        return "twse"

    def fetch_daily_price(self, symbol: str, start_date: str, end_date: str) -> RawResponseEnvelope:
        # TWSE uses date format YYYYMMDD
        twse_date = start_date.replace("-", "")
        params = {
            "date": twse_date,
            "stockNo": symbol,
            "response": "json",
        }
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
        twse_date = start_date.replace("-", "")
        url = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
        params = {"date": twse_date, "response": "json"}
        payload = self.transport.request(url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=url,
            params=params,
            status_code=200,
            raw_payload=payload,
        )

    def fetch_margin(self, symbol: str, start_date: str, end_date: str) -> RawResponseEnvelope:
        twse_date = start_date.replace("-", "")
        url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGIN"
        params = {"date": twse_date, "response": "json"}
        payload = self.transport.request(url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=url,
            params=params,
            status_code=200,
            raw_payload=payload,
        )
