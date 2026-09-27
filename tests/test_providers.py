"""Comprehensive Provider, Transport, Retry, Backoff, and Security Tests."""

import hashlib
from typing import Any, Dict, Tuple

from qmo.providers.finmind import FinMindProvider
from qmo.providers.protocols import ProviderProtocol, RawResponseEnvelope
from qmo.providers.tpex import TpexProvider
from qmo.providers.transport import HttpTransport, parse_retry_after
from qmo.providers.twse import TwseProvider


def test_provider_protocol_runtime_check() -> None:
    """Verify providers satisfy ProviderProtocol."""
    finmind = FinMindProvider()
    twse = TwseProvider()
    tpex = TpexProvider()

    assert isinstance(finmind, ProviderProtocol)
    assert isinstance(twse, ProviderProtocol)
    assert isinstance(tpex, ProviderProtocol)


def test_raw_response_envelope_sha256_exact_digest() -> None:
    """Verify RawResponseEnvelope computes exact SHA-256 digest on raw bytes."""
    raw_bytes = b'{"msg": "success", "data": [{"stock_id": "2330", "close": 980.0}]}'
    expected_hash = hashlib.sha256(raw_bytes).hexdigest()

    envelope = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=raw_bytes,
    )
    assert envelope.content_hash == expected_hash
    assert envelope.raw_body_str == raw_bytes.decode("utf-8")

    # Verify content mutation changes hash deterministically
    raw_bytes_modified = b'{"msg": "success", "data": [{"stock_id": "2330", "close": 985.0}]}'
    envelope_mod = RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://api.finmindtrade.com/api/v4/data",
        params={"data_id": "2330"},
        status_code=200,
        raw_body_bytes=raw_bytes_modified,
    )
    assert envelope_mod.content_hash != expected_hash


def test_token_masking_security() -> None:
    """Verify sensitive tokens are masked in envelope parameters."""
    raw_bytes = b'{"msg": "success", "data": []}'

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        assert params.get("token") == "secret_api_key_12345"
        return 200, {"Content-Type": "application/json"}, raw_bytes

    transport = HttpTransport(request_func=mock_request)
    provider = FinMindProvider(transport=transport, api_token="secret_api_key_12345")
    envelope = provider.fetch_daily_price("2330", "2026-09-01", "2026-09-02")

    assert envelope.params["token"] == "***MASKED***"
    assert envelope.raw_body_bytes == raw_bytes


def test_transport_status_code_classification_and_sleep_inject() -> None:
    """Verify Transport handles 500 status_code retries with sleep_func injection."""
    attempts = 0
    sleep_calls = []

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return 500, {}, b"Server error"
        return 200, {"Content-Type": "application/json"}, b'{"msg": "success"}'

    def mock_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    transport = HttpTransport(
        max_retries=2,
        backoff_factor=0.5,
        request_func=mock_request,
        sleep_func=mock_sleep,
    )
    res = transport.execute("https://api.finmindtrade.com/api/v4/data")
    assert attempts == 2
    assert res.status_code == 200
    assert len(sleep_calls) >= 1
    assert sleep_calls[0] == 0.5  # 0.5 * (2**0)


def test_parse_retry_after_integer_and_http_date() -> None:
    """Test parse_retry_after helper supporting integer seconds and HTTP-date strings."""
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after("") is None
    # Test valid RFC-1123 HTTP-date
    res = parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT")
    assert res is not None or res == 0.0


def test_twse_t86_institutional_endpoint() -> None:
    """Verify TWSE Provider uses the T86 endpoint for institutional investor report."""

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        assert "T86" in url
        return 200, {"Content-Type": "application/json"}, b'{"stat": "OK", "data": []}'

    transport = HttpTransport(request_func=mock_request)
    provider = TwseProvider(transport=transport)
    envelope = provider.fetch_institutional_flow("2330", "2026-09-27", "2026-09-27")

    assert "T86" in envelope.endpoint
    assert envelope.status_code == 200
