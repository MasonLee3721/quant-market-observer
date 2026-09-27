"""Immutable Raw Snapshot Store implementation with sidecar metadata."""

import hashlib
import json
from pathlib import Path
from typing import Tuple

from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.validation import validate_safe_identifier


class RawSnapshotStore:
    """Stores raw provider response payloads with byte-for-byte content-addressed immutability."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def save(self, envelope: RawResponseEnvelope, dataset_name: str) -> Tuple[str, Path]:
        """Save raw payload to immutable path keyed by content SHA-256 hash.

        Preserves exact raw payload bytes byte-for-byte. Returns (content_hash, raw_file_path).
        """
        validate_safe_identifier(dataset_name, "dataset_name")

        raw_bytes = envelope.raw_body_bytes
        if not raw_bytes:
            raise ValueError("Cannot store raw payload with empty raw_body_bytes")

        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        dataset_dir = self.base_dir / dataset_name
        dataset_dir.mkdir(parents=True, exist_ok=True)

        raw_file = dataset_dir / f"{content_hash}.raw"
        meta_file = dataset_dir / f"{content_hash}.meta.json"

        # Byte-for-byte immutability & corruption verification
        if raw_file.exists() and meta_file.exists():
            existing_bytes = raw_file.read_bytes()
            existing_hash = hashlib.sha256(existing_bytes).hexdigest()
            if existing_hash == content_hash:
                # Content matches perfectly byte-for-byte: skip re-writing
                return content_hash, raw_file

        # Write exact raw_bytes byte-for-byte
        raw_file.write_bytes(raw_bytes)

        # Write metadata sidecar
        meta_dict = {
            "provider_name": envelope.provider_name,
            "endpoint": envelope.endpoint,
            "status_code": envelope.status_code,
            "retrieved_at": envelope.retrieved_at,
            "content_hash": content_hash,
            "params": envelope.params,
            "raw_body_str": envelope.raw_body_str,
        }
        meta_json = json.dumps(meta_dict, indent=2, ensure_ascii=False).encode("utf-8")
        meta_file.write_bytes(meta_json + b"\n")

        return content_hash, raw_file
