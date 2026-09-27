"""Provider Contract, Transport, Retry, and Envelope Tests."""

import pytest

from qmo.providers.exceptions import NetworkError
from qmo.providers.finmind import FinMindProvider
from qmo.providers.protocols import ProviderProtocol, RawResponseEnvelope
from qmo.providers.tpex import TpexProvider
from qmo.providers.transport import HttpTransport
from qmo.providers.twse import TwseProvider


def test_provider_protocol_runtime_check() -> None:
    """Verify providers satisfy ProviderProtocol."""
    finmind = FinMindProvider()
    twse = TwseProvider()
    tpex = TpexProvider()

    assert isinstance(finmind, ProviderProtocol)
    assert isinstance(twse, ProviderProtocol)
    assert isinstance(tpex, ProviderProtocol)


def test_raw_response_envelope_content_hash() -> None:
    """Verify raw response envelope generates SHA-256 content hash automatically."""
    payload = {"msg": "success", "data": [{"stock_id": "2330", "close": 100.0}]}
    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "2330"},
        status_code=200,
        raw_payload=payload,
    )
    assert len(envelope.content_hash) == 64  # SHA-256 hex digest length
    assert envelope.provider_name == "finmind"


def test_transport_fixture_replay() -> None:
    """Test transport using mock request function fixture replay."""
    mock_payload = {"msg": "success", "data": []}

    def mock_request(url: str, params: None = None, headers: None = None) -> dict:
        return mock_payload

    transport = HttpTransport(request_func=mock_request)
    provider = FinMindProvider(transport=transport)
    envelope = provider.fetch_daily_price("2330", "2026-09-01", "2026-09-02")

    assert envelope.status_code == 200
    assert envelope.raw_payload == mock_payload


def test_transport_error_handling() -> None:
    """Test transport error handling for network errors."""
    transport = HttpTransport()
    provider = FinMindProvider(transport=transport)

    with pytest.raises(NetworkError):
        provider.fetch_daily_price("2330", "2026-09-01", "2026-09-02")
