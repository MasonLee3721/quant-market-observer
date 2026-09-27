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
    """Internal HTTP Response representation."""

    def __init__(self, status_code: int, headers: Dict[str, str], raw_body: str) -> None:
        self.status_code = status_code
        self.headers = headers
        self.raw_body = raw_body

    def json(self) -> Dict[str, Any]:
        """Parse raw body as JSON dict."""
        res = json.loads(self.raw_body)
        return cast(Dict[str, Any], res)


class HttpTransport:
    """HTTP Transport with retry loop, backoff, rate limit, and real network support."""

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        min_request_interval: float = 0.1,
        timeout: float = 10.0,
        request_func: Optional[Callable[..., Tuple[int, Dict[str, str], str]]] = None,
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

        # Build full URL with parameters if present
        if params_dict:
            query_str = urllib.parse.urlencode(params_dict)
            full_url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"
        else:
            full_url = url

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            # Enforce rate limiting
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            self._last_request_time = time.time()

            try:
                if self._request_func is not None:
                    status_code, resp_headers, body_str = self._request_func(
                        full_url, params=params_dict, headers=headers_dict
                    )
                    return HttpResponse(status_code, resp_headers, body_str)

                # Real urllib HTTP Request
                req = urllib.request.Request(full_url, headers=headers_dict)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status_code = resp.getcode()
                    resp_headers = dict(resp.info())
                    body_bytes = resp.read()
                    body_str = body_bytes.decode("utf-8", errors="replace")
                    return HttpResponse(status_code, resp_headers, body_str)

            except urllib.error.HTTPError as e:
                status_code = e.code
                if status_code == 429:
                    last_exception = RateLimitError(
                        f"Rate limit exceeded (HTTP 429) for {url}", provider="transport"
                    )
                elif status_code >= 500:
                    last_exception = ProviderError(
                        f"Server error (HTTP {status_code}) for {url}",
                        provider="transport",
                        status_code=status_code,
                    )
                else:
                    # Non-retryable client error (400, 403, 404)
                    raise ProviderError(
                        f"HTTP Client Error {status_code} for {url}",
                        provider="transport",
                        status_code=status_code,
                    ) from e

            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_exception = NetworkError(f"Network error: {e}", provider="transport")

            # Exponential backoff sleep before retry if attempts remain
            if attempt < self.max_retries:
                sleep_time = self.backoff_factor * (2**attempt)
                time.sleep(sleep_time)

        if last_exception:
            raise last_exception
        raise NetworkError(f"Request failed after {self.max_retries} retries", provider="transport")
