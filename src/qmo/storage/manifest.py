"""Batch Manifest Data Model adhering to M1 Storage Specification."""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class BatchStatus(str, Enum):
    """Execution status for batch pipeline lifecycle."""

    STAGED = "STAGED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class BatchManifest(BaseModel):
    """Metadata manifest tracking source hash, record count, and publish status."""

    batch_id: str
    dataset: str
    source_raw_hashes: List[str] = Field(default_factory=list)
    schema_version: str = "schema-v0.1"
    record_count: int = Field(default=0, ge=0)
    partition_date_range: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: BatchStatus = BatchStatus.STAGED
    published_filepaths: List[str] = Field(default_factory=list)
    manifest_hash: str = ""

    @field_validator("created_at")
    @classmethod
    def validate_utc_iso(cls, v: str) -> str:
        if v:
            iso_str = v.replace("Z", "+00:00") if v.endswith("Z") else v
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                raise ValueError(f"created_at must be UTC timezone-aware, got: {v}")
        return v

    def compute_manifest_hash(self) -> str:
        """Compute deterministic SHA-256 digest of batch manifest metadata."""
        data_dict: Dict[str, Any] = {
            "batch_id": self.batch_id,
            "dataset": self.dataset,
            "source_raw_hashes": sorted(self.source_raw_hashes),
            "schema_version": self.schema_version,
            "record_count": self.record_count,
            "partition_date_range": self.partition_date_range,
            "created_at": self.created_at,
            "status": self.status.value,
        }
        serialized = json.dumps(data_dict, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        if not self.manifest_hash:
            self.manifest_hash = self.compute_manifest_hash()
