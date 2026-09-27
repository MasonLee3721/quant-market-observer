"""Provider Protocol and Envelope Definition."""

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RawResponseEnvelope(BaseModel):
    """Unmodified Raw Response Envelope preserving raw bytes and masked metadata."""

    provider_name: str
    endpoint: str
    params: Dict[str, Any]  # Masked parameters (safe for snapshot logging)
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    raw_body_bytes: bytes = b""  # Exact raw response bytes
    content_hash: str = ""  # SHA-256 on raw_body_bytes

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash and self.raw_body_bytes:
            self.content_hash = hashlib.sha256(self.raw_body_bytes).hexdigest()

    @property
    def raw_body_str(self) -> str:
        """Decode raw body bytes using utf-8 with replacement for invalid bytes."""
        return self.raw_body_bytes.decode("utf-8", errors="replace")


@runtime_checkable
class ProviderProtocol(Protocol):
    """Protocol defining data provider interface."""

    @property
    def provider_name(self) -> str: ...

    def fetch_daily_price(
        self, symbol: str, start_date: str, end_date: str
    ) -> RawResponseEnvelope: ...

    def fetch_institutional_flow(
        self, symbol: str, start_date: str, end_date: str
    ) -> RawResponseEnvelope: ...

    def fetch_margin(self, symbol: str, start_date: str, end_date: str) -> RawResponseEnvelope: ...
