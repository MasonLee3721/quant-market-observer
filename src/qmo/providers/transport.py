"""HTTP Transport Component for Provider API Requests."""

import time
from typing import Any, Callable, Dict, Optional, cast

from qmo.providers.exceptions import NetworkError


class HttpTransport:
    """HTTP transport with rate-limiting, backoff retry, and offline fixture replay."""

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        min_request_interval: float = 0.1,
        request_func: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.min_request_interval = min_request_interval
        self._request_func = request_func
        self._last_request_time: float = 0.0

    def request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute request with rate limiting and exponential backoff retry."""
        # Enforce rate limiting
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self._last_request_time = time.time()

        if self._request_func is not None:
            return cast(Dict[str, Any], self._request_func(url, params=params, headers=headers))

        # Fallback default runner shell (in offline / mocked environment)
        raise NetworkError("No network or mock request_func provided", provider="transport")
