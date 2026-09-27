"""HTTP Transport with Rate-Limiting, Backoff, Status Classification, and Security."""

import email.utils
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple, cast

from qmo.providers.exceptions import (
    NetworkError,
    ProviderError,
    RateLimitError,
)


def mask_sensitive_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Mask sensitive keys like 'token' or 'api_key' in query parameters."""
    masked = dict(params)
    for key in masked:
        if any(sec in key.lower() for sec in ["token", "key", "secret", "password"]):
            masked[key] = "***MASKED***"
    return masked


def parse_retry_after(
    retry_after_str: str, now_func: Optional[Callable[[], datetime]] = None
) -> Optional[float]:
    """Parse Retry-After header which can be integer seconds or HTTP-date string."""
    if not retry_after_str:
        return None
    if retry_after_str.isdigit():
        return float(retry_after_str)
    try:
        dt = email.utils.parsedate_to_datetime(retry_after_str)
        now = now_func() if now_func else datetime.now(timezone.utc)
        diff = (dt - now).total_seconds()
        return max(0.0, diff)
    except Exception:
        return None


class HttpResponse:
    """Internal HTTP Response representation preserving raw bytes."""

    def __init__(self, status_code: int, headers: Dict[str, str], raw_bytes: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.raw_bytes = raw_bytes

    @property
    def raw_body_str(self) -> str:
        return self.raw_bytes.decode("utf-8", errors="replace")

    def json(self) -> Dict[str, Any]:
        """Parse raw body as JSON dict."""
        res = json.loads(self.raw_body_str)
        return cast(Dict[str, Any], res)


class HttpTransport:
    """HTTP Transport with retry loop, backoff, rate limit, and real network support."""

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        min_request_interval: float = 0.1,
        timeout: float = 10.0,
        request_func: Optional[Callable[..., Tuple[int, Dict[str, str], bytes]]] = None,
        sleep_func: Optional[Callable[[float], None]] = None,
        clock_func: Optional[Callable[[], float]] = None,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.min_request_interval = min_request_interval
        self.timeout = timeout
        self._request_func = request_func
        self._sleep_func = sleep_func or time.sleep
        self._clock_func = clock_func or time.monotonic
        self._last_request_time: float = 0.0

    def execute(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        """Execute HTTP request with status classification and exponential backoff retries."""
        params_dict = params or {}
        headers_dict = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QuantMarketObserver/1.0"
        }

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            now = self._clock_func()
            elapsed = now - self._last_request_time
            if elapsed < self.min_request_interval:
                self._sleep_func(self.min_request_interval - elapsed)
            self._last_request_time = self._clock_func()

            status_code = 0
            resp_headers: Dict[str, str] = {}
            body_bytes = b""

            try:
                if self._request_func is not None:
                    status_code, resp_headers, body_bytes = self._request_func(
                        url, params_dict, headers_dict
                    )
                else:
                    if params_dict:
                        query_str = urllib.parse.urlencode(params_dict)
                        full_url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"
                    else:
                        full_url = url

                    req = urllib.request.Request(full_url, headers=headers_dict)
                    try:
                        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                            status_code = resp.getcode()
                            resp_headers = dict(resp.info())
                            body_bytes = resp.read()
                    except urllib.error.HTTPError as e:
                        status_code = e.code
                        resp_headers = dict(e.headers) if e.headers else {}
                        body_bytes = e.read() if hasattr(e, "read") else b""

            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_exception = NetworkError(f"Network error: {e}", provider="transport")
                if attempt < self.max_retries:
                    self._sleep_func(self.backoff_factor * (2**attempt))
                    continue
                else:
                    break

            # Unified Single Status Code Classification Path
            if 200 <= status_code < 300:
                return HttpResponse(status_code, resp_headers, body_bytes)

            if status_code == 429:
                retry_after_hdr = resp_headers.get("Retry-After", "")
                parsed_delay = parse_retry_after(retry_after_hdr)
                delay = (
                    parsed_delay
                    if parsed_delay is not None
                    else (self.backoff_factor * (2**attempt))
                )
                last_exception = RateLimitError(
                    f"Rate limit exceeded (HTTP 429) for {url}", provider="transport"
                )
                if attempt < self.max_retries:
                    self._sleep_func(delay)
                    continue
                else:
                    break

            elif status_code >= 500:
                last_exception = ProviderError(
                    f"Server error (HTTP {status_code}) for {url}",
                    provider="transport",
                    status_code=status_code,
                )
                if attempt < self.max_retries:
                    self._sleep_func(self.backoff_factor * (2**attempt))
                    continue
                else:
                    break

            else:
                # Fast fail on non-retryable 4xx client errors (400, 403, 404)
                raise ProviderError(
                    f"HTTP Client Error {status_code} for {url}",
                    provider="transport",
                    status_code=status_code,
                )

        if last_exception:
            raise last_exception
        raise NetworkError(f"Request failed after {self.max_retries} retries", provider="transport")
