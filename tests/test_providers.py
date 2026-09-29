"""Comprehensive Provider, Transport, Retry, Backoff, and Security Tests."""

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import pytest

from qmo.providers.exceptions import NetworkError, ProviderError, RateLimitError
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


def test_transport_status_code_classification_500_retry() -> None:
    """Verify Transport handles 500 status_code retries with sleep_func injection."""
    attempts = 0
    sleep_calls = []
    clock_time = 0.0

    def mock_clock() -> float:
        nonlocal clock_time
        clock_time += 1.0
        return clock_time

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
        clock_func=mock_clock,
    )
    res = transport.execute("https://api.finmindtrade.com/api/v4/data")
    assert attempts == 2
    assert res.status_code == 200
    assert sleep_calls == [0.5]


def test_transport_429_rate_limit_retries_and_raises() -> None:
    """Verify HTTP 429 status code retries up to max_retries and raises RateLimitError."""
    attempts = 0
    sleep_calls = []
    clock_time = 0.0

    def mock_clock() -> float:
        nonlocal clock_time
        clock_time += 1.0
        return clock_time

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        nonlocal attempts
        attempts += 1
        return 429, {"Retry-After": "2"}, b'{"msg": "too many requests"}'

    def mock_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    transport = HttpTransport(
        max_retries=2,
        backoff_factor=0.5,
        request_func=mock_request,
        sleep_func=mock_sleep,
        clock_func=mock_clock,
    )
    with pytest.raises(RateLimitError):
        transport.execute("https://api.finmindtrade.com/api/v4/data")

    assert attempts == 3  # 1 initial + 2 retries
    assert sleep_calls == [2.0, 2.0]  # Respects Retry-After header delay


def test_transport_404_fast_fail_immediately() -> None:
    """Verify HTTP 404 client error raises ProviderError immediately without retrying."""
    attempts = 0

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        nonlocal attempts
        attempts += 1
        return 404, {}, b'{"msg": "not found"}'

    transport = HttpTransport(max_retries=3, request_func=mock_request)
    with pytest.raises(ProviderError) as exc_info:
        transport.execute("https://api.finmindtrade.com/api/v4/data")

    assert attempts == 1  # Fast fail without retrying!
    assert exc_info.value.status_code == 404


def test_transport_network_error_backoff_and_exhaustion() -> None:
    """Verify connection failure backoffs and raises NetworkError after retries."""
    attempts = 0

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        nonlocal attempts
        attempts += 1
        raise OSError("Connection refused")

    transport = HttpTransport(max_retries=2, backoff_factor=0.1, request_func=mock_request)
    with pytest.raises(NetworkError):
        transport.execute("https://api.finmindtrade.com/api/v4/data")

    assert attempts == 3  # 1 initial + 2 retries


def test_parse_retry_after_exact_http_date_with_fixed_clock() -> None:
    """Test parse_retry_after with fixed UTC clock injection."""
    fixed_now = datetime(2026, 9, 27, 3, 0, 0, tzinfo=timezone.utc)

    def fixed_clock() -> datetime:
        return fixed_now

    assert parse_retry_after("60", now_func=fixed_clock) == 60.0

    # Retry-After: 0.0 is valid zero delay (not falsy override)
    assert parse_retry_after("0", now_func=fixed_clock) == 0.0

    http_date = "Sun, 27 Sep 2026 03:02:00 GMT"
    diff = parse_retry_after(http_date, now_func=fixed_clock)
    assert diff == 120.0


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


def test_twse_fetch_market_daily_price_endpoint() -> None:
    """Verify TWSE Provider uses MI_INDEX endpoint with correct params."""

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        assert "MI_INDEX" in url
        assert params["date"] == "20260924"
        assert params["type"] == "ALLBUT0999"
        assert params["response"] == "json"
        return 200, {"Content-Type": "application/json"}, b'{"stat": "OK", "tables": []}'

    transport = HttpTransport(request_func=mock_request)
    provider = TwseProvider(transport=transport)
    envelope = provider.fetch_market_daily_price("2026-09-24")

    assert "MI_INDEX" in envelope.endpoint
    assert envelope.status_code == 200
    assert envelope.params["date"] == "20260924"


def test_tpex_fetch_market_daily_price_endpoint() -> None:
    """Verify TPEx Provider uses stk_quote_result.php with ROC date conversion."""

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        assert "stk_quote_result.php" in url
        assert params["d"] == "115/09/24"
        assert params["l"] == "zh-tw"
        assert params["s"] == "0,asc,0"
        return 200, {"Content-Type": "application/json"}, b'{"stat": "OK", "aaData": []}'

    transport = HttpTransport(request_func=mock_request)
    provider = TpexProvider(transport=transport)
    envelope = provider.fetch_market_daily_price("2026-09-24")

    assert "stk_quote_result.php" in envelope.endpoint
    assert envelope.status_code == 200
    assert envelope.params["d"] == "115/09/24"


def test_twse_margin_endpoint() -> None:
    """Verify TWSE Provider uses TWT93U endpoint for margin trading report."""

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        assert "TWT93U" in url
        assert params["date"] == "20260924"
        assert params["response"] == "json"
        return 200, {"Content-Type": "application/json"}, b'{"stat": "OK", "tables": []}'

    transport = HttpTransport(request_func=mock_request)
    provider = TwseProvider(transport=transport)
    envelope = provider.fetch_margin("2330", "2026-09-24", "2026-09-24")

    assert "TWT93U" in envelope.endpoint
    assert envelope.status_code == 200


def test_tpex_institutional_and_margin_endpoints() -> None:
    """Verify TPEx Provider institutional and margin endpoints convert Gregorian to ROC date."""

    called_urls = []

    def mock_request(
        url: str, params: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, str], bytes]:
        called_urls.append((url, params))
        return 200, {"Content-Type": "application/json"}, b'{"stat": "OK", "aaData": []}'

    transport = HttpTransport(request_func=mock_request)
    provider = TpexProvider(transport=transport)

    env_inst = provider.fetch_institutional_flow("6488", "2026-09-24", "2026-09-24")
    assert "insti/dailyTrade" in env_inst.endpoint
    assert env_inst.params["d"] == "115/09/24"
    assert env_inst.params["type"] == "Daily"

    env_margin = provider.fetch_margin("6488", "2026-09-24", "2026-09-24")
    assert "margin/balance" in env_margin.endpoint
    assert env_margin.params["d"] == "115/09/24"
