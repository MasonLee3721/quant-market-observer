"""Comprehensive Provider, Transport, Retry, Backoff, and Security Tests."""

from typing import Any, Dict, Tuple

import pytest

from qmo.providers.exceptions import ProviderError, RateLimitError
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


def test_raw_response_envelope_sha256_content_hash() -> None:
    """Verify RawResponseEnvelope computes SHA-256 on unparsed raw_body bytes."""
    raw_json_str = '{"msg": "success", "data": [{"stock_id": "2330", "close": 980.0}]}'
    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "2330"},
        status_code=200,
        raw_body=raw_json_str,
    )
    assert len(envelope.content_hash) == 64
    assert envelope.provider_name == "finmind"


def test_token_masking_security() -> None:
    """Verify sensitive tokens are masked in envelope parameters."""
    raw_json_str = '{"msg": "success", "data": []}'

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], str]:
        # Sensitive token MUST be present in outbound request
        assert params.get("token") == "secret_api_key_12345"
        return 200, {"Content-Type": "application/json"}, raw_json_str

    transport = HttpTransport(request_func=mock_request)
    provider = FinMindProvider(transport=transport, api_token="secret_api_key_12345")
    envelope = provider.fetch_daily_price("2330", "2026-09-01", "2026-09-02")

    # Envelope params MUST be masked to prevent credential leaks in snapshots
    assert envelope.params["token"] == "***MASKED***"
    assert envelope.raw_body == raw_json_str


def test_transport_retry_and_backoff_success() -> None:
    """Test exponential backoff retry loop recovering on 2nd attempt."""
    attempts = 0
    raw_json_str = '{"msg": "success", "data": []}'

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise pytest.importorskip("urllib.error").HTTPError(
                url,
                500,
                "Internal Server Error",
                {},
                None,  # type: ignore[arg-type]
            )
        return 200, {"Content-Type": "application/json"}, raw_json_str

    transport = HttpTransport(max_retries=2, backoff_factor=0.01, request_func=mock_request)
    res = transport.execute("https://api.finmindtrade.com/api/v4/data")
    assert attempts == 2
    assert res.status_code == 200
    assert res.raw_body == raw_json_str


def test_transport_rate_limit_error_429() -> None:
    """Test HTTP 429 rate limit exception raising."""

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], str]:
        raise pytest.importorskip("urllib.error").HTTPError(
            url,
            429,
            "Too Many Requests",
            {},
            None,  # type: ignore[arg-type]
        )

    transport = HttpTransport(max_retries=1, backoff_factor=0.01, request_func=mock_request)
    with pytest.raises(RateLimitError):
        transport.execute("https://api.finmindtrade.com/api/v4/data")


def test_transport_non_retryable_404_error() -> None:
    """Test fast fail on non-retryable 404 client error without retrying."""
    attempts = 0

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], str]:
        nonlocal attempts
        attempts += 1
        raise pytest.importorskip("urllib.error").HTTPError(
            url,
            404,
            "Not Found",
            {},
            None,  # type: ignore[arg-type]
        )

    transport = HttpTransport(max_retries=3, backoff_factor=0.01, request_func=mock_request)
    with pytest.raises(ProviderError) as exc_info:
        transport.execute("https://api.finmindtrade.com/api/v4/data")

    assert attempts == 1  # Fast fail without wasteful retries
    assert exc_info.value.status_code == 404


def test_twse_t86_institutional_endpoint() -> None:
    """Verify TWSE Provider uses the T86 endpoint for institutional investor report."""

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], str]:
        assert "T86" in url
        return 200, {"Content-Type": "application/json"}, '{"stat": "OK", "data": []}'

    transport = HttpTransport(request_func=mock_request)
    provider = TwseProvider(transport=transport)
    envelope = provider.fetch_institutional_flow("2330", "2026-09-27", "2026-09-27")

    assert "T86" in envelope.endpoint
    assert envelope.status_code == 200
