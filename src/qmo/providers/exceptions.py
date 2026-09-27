"""Custom Exception Hierarchy for Data Providers."""


class ProviderError(Exception):
    """Base exception for all provider operations."""

    def __init__(self, message: str, provider: str = "", status_code: int = 0) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class RateLimitError(ProviderError):
    """Raised when provider hits API rate limits (e.g. HTTP 429)."""

    def __init__(self, message: str = "Rate limit exceeded", provider: str = "") -> None:
        super().__init__(message, provider=provider, status_code=429)


class NetworkError(ProviderError):
    """Raised on connection timeout or network failure."""

    pass


class SchemaValidationError(ProviderError):
    """Raised when raw response schema does not match expectation."""

    pass
