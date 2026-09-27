"""Immutable Raw Snapshot Store implementation."""

import hashlib
import json
from pathlib import Path
from typing import Dict, Tuple

from qmo.providers.protocols import RawResponseEnvelope


class RawSnapshotStore:
    """Stores raw provider response payloads with content-addressed immutability."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def save(self, envelope: RawResponseEnvelope, dataset_name: str) -> Tuple[str, Path]:
        """Save raw payload to immutable path keyed by content SHA-256 hash.

        Returns (content_hash, file_path). If file exists, skips re-writing.
        """
        raw_bytes = envelope.raw_body_bytes
        if not raw_bytes:
            raise ValueError("Cannot store raw payload with empty raw_body_bytes")

        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        dataset_dir = self.base_dir / dataset_name
        dataset_dir.mkdir(parents=True, exist_ok=True)

        target_file = dataset_dir / f"{content_hash}.json"

        # Content-addressed immutability check: skip re-writing if exists
        if not target_file.exists():
            metadata_dict: Dict[str, str | int | Dict[str, str]] = {
                "provider_name": envelope.provider_name,
                "endpoint": envelope.endpoint,
                "status_code": envelope.status_code,
                "retrieved_at": envelope.retrieved_at,
                "content_hash": content_hash,
                "params": envelope.params,
                "raw_body": envelope.raw_body_str,
            }
            target_file.write_text(
                json.dumps(metadata_dict, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        return content_hash, target_file
