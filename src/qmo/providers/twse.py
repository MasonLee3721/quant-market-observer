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
        twse_date = start_date.replace("-", "")
        params = {
            "date": twse_date,
            "stockNo": symbol,
            "response": "json",
        }
        res = self.transport.execute(self.base_url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=self.base_url,
            params=params,
            status_code=res.status_code,
            headers=res.headers,
            raw_body=res.raw_body,
        )

    def fetch_institutional_flow(
        self, symbol: str, start_date: str, end_date: str
    ) -> RawResponseEnvelope:
        twse_date = start_date.replace("-", "")
        # Official TWSE Institutional Investor Buy/Sell Daily Report endpoint is T86
        url = "https://www.twse.com.tw/rwd/zh/afterTrading/T86"
        params = {
            "date": twse_date,
            "selectType": "ALLBUT0999",
            "response": "json",
        }
        res = self.transport.execute(url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=url,
            params=params,
            status_code=res.status_code,
            headers=res.headers,
            raw_body=res.raw_body,
        )

    def fetch_margin(self, symbol: str, start_date: str, end_date: str) -> RawResponseEnvelope:
        twse_date = start_date.replace("-", "")
        url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGIN"
        params = {
            "date": twse_date,
            "selectType": "ALL",
            "response": "json",
        }
        res = self.transport.execute(url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=url,
            params=params,
            status_code=res.status_code,
            headers=res.headers,
            raw_body=res.raw_body,
        )
