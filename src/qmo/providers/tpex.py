"""TPEx (Taipei Exchange) Data Provider Adapter."""

from typing import Optional

from qmo.providers.protocols import RawResponseEnvelope
from qmo.providers.transport import HttpTransport


class TpexProvider:
    """Provider for TPEx (OTC market) official data."""

    def __init__(self, transport: Optional[HttpTransport] = None) -> None:
        self.transport = transport or HttpTransport()
        self.base_url = (
            "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php"
        )

    @property
    def provider_name(self) -> str:
        return "tpex"

    def fetch_daily_price(self, symbol: str, start_date: str, end_date: str) -> RawResponseEnvelope:
        # Converts YYYY-MM-DD to ROC Date format (e.g. 113/09)
        parts = start_date.split("-")
        roc_year = int(parts[0]) - 1911
        roc_date = f"{roc_year}/{parts[1]}"
        params = {
            "d": roc_date,
            "stkno": symbol,
            "l": "zh-tw",
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
        parts = start_date.split("-")
        roc_year = int(parts[0]) - 1911
        roc_date = f"{roc_year}/{parts[1]}/{parts[2]}"
        url = "https://www.tpex.org.tw/web/stock/3shares/3shares_result.php"
        params = {"d": roc_date, "l": "zh-tw"}
        payload = self.transport.request(url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=url,
            params=params,
            status_code=200,
            raw_payload=payload,
        )

    def fetch_margin(self, symbol: str, start_date: str, end_date: str) -> RawResponseEnvelope:
        parts = start_date.split("-")
        roc_year = int(parts[0]) - 1911
        roc_date = f"{roc_year}/{parts[1]}/{parts[2]}"
        url = "https://www.tpex.org.tw/web/stock/margin_trading/margin_bal/margin_bal_result.php"
        params = {"d": roc_date, "l": "zh-tw"}
        payload = self.transport.request(url, params=params)
        return RawResponseEnvelope(
            provider_name=self.provider_name,
            endpoint=url,
            params=params,
            status_code=200,
            raw_payload=payload,
        )
