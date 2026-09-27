"""Real HTTP Transport with Rate-Limiting, Exponential Backoff, and Security."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
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
    ) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.min_request_interval = min_request_interval
        self.timeout = timeout
        self._request_func = request_func
        self._last_request_time: float = 0.0

    def execute(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        """Execute HTTP request with exponential backoff retries."""
        params_dict = params or {}
        headers_dict = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QuantMarketObserver/1.0"
        }

        if params_dict:
            query_str = urllib.parse.urlencode(params_dict)
            full_url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"
        else:
            full_url = url

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            self._last_request_time = time.time()

            try:
                if self._request_func is not None:
                    status_code, resp_headers, body_bytes = self._request_func(
                        full_url, params=params_dict, headers=headers_dict
                    )
                    return HttpResponse(status_code, resp_headers, body_bytes)

                req = urllib.request.Request(full_url, headers=headers_dict)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status_code = resp.getcode()
                    resp_headers = dict(resp.info())
                    body_bytes = resp.read()
                    return HttpResponse(status_code, resp_headers, body_bytes)

            except urllib.error.HTTPError as e:
                status_code = e.code
                headers_info = dict(e.headers) if e.headers else {}
                if status_code == 429:
                    retry_after = headers_info.get("Retry-After")
                    delay = (
                        float(retry_after)
                        if retry_after and retry_after.isdigit()
                        else (self.backoff_factor * (2**attempt))
                    )
                    last_exception = RateLimitError(
                        f"Rate limit exceeded (HTTP 429) for {url}", provider="transport"
                    )
                    if attempt < self.max_retries:
                        time.sleep(delay)
                        continue
                elif status_code >= 500:
                    last_exception = ProviderError(
                        f"Server error (HTTP {status_code}) for {url}",
                        provider="transport",
                        status_code=status_code,
                    )
                else:
                    raise ProviderError(
                        f"HTTP Client Error {status_code} for {url}",
                        provider="transport",
                        status_code=status_code,
                    ) from e

            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_exception = NetworkError(f"Network error: {e}", provider="transport")

            if attempt < self.max_retries:
                sleep_time = self.backoff_factor * (2**attempt)
                time.sleep(sleep_time)

        if last_exception:
            raise last_exception
        raise NetworkError(f"Request failed after {self.max_retries} retries", provider="transport")
