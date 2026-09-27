"""Provider Protocol and Envelope Definition."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RawResponseEnvelope(BaseModel):
    """Unmodified Raw Response Envelope from Data Providers."""

    provider_name: str
    endpoint: str
    params: Dict[str, Any]
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status_code: int
    raw_payload: Any
    content_hash: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            payload_bytes = json.dumps(self.raw_payload, sort_keys=True).encode("utf-8")
            self.content_hash = hashlib.sha256(payload_bytes).hexdigest()


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
