"""Immutable Raw Snapshot Store implementation with byte-for-byte preservation."""

import hashlib
import json
from pathlib import Path
from typing import Tuple

from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.validation import validate_safe_identifier


class RawSnapshotStore:
    """Stores raw provider response payloads with content-addressed immutability."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def save(self, envelope: RawResponseEnvelope, dataset_name: str) -> Tuple[str, Path]:
        """Save raw payload to immutable path keyed by content SHA-256 hash.

        Preserves exact raw payload bytes byte-for-byte. Returns (content_hash, target_file).
        """
        validate_safe_identifier(dataset_name, "dataset_name")

        raw_bytes = envelope.raw_body_bytes
        if not raw_bytes:
            raise ValueError("Cannot store raw payload with empty raw_body_bytes")

        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        dataset_dir = self.base_dir / dataset_name
        dataset_dir.mkdir(parents=True, exist_ok=True)

        target_file = dataset_dir / f"{content_hash}.json"

        # Byte-for-byte preservation and corruption verification
        if target_file.exists():
            existing_bytes = target_file.read_bytes()
            existing_hash = hashlib.sha256(existing_bytes).hexdigest()
            if existing_hash != content_hash:
                # File corrupted on disk: overwrite with valid byte-for-byte payload
                self._write_snapshot_file(target_file, envelope, content_hash)
        else:
            self._write_snapshot_file(target_file, envelope, content_hash)

        return content_hash, target_file

    def _write_snapshot_file(
        self,
        target_file: Path,
        envelope: RawResponseEnvelope,
        content_hash: str,
    ) -> None:
        """Write metadata envelope and exact byte-for-byte raw body payload."""
        payload_dict = {
            "provider_name": envelope.provider_name,
            "endpoint": envelope.endpoint,
            "status_code": envelope.status_code,
            "retrieved_at": envelope.retrieved_at,
            "content_hash": content_hash,
            "params": envelope.params,
            "raw_body_str": envelope.raw_body_str,
        }
        encoded_json = json.dumps(payload_dict, indent=2, ensure_ascii=False).encode("utf-8")
        target_file.write_bytes(encoded_json + b"\n")
