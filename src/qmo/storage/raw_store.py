"""Immutable Raw Snapshot Store implementation with sidecar metadata."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.validation import validate_safe_identifier


class RawSnapshotStore:
    """Stores raw provider response payloads with byte-for-byte content-addressed immutability."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def load_matching(
        self, dataset_name: str, required_params: Dict[str, Any]
    ) -> Optional[RawResponseEnvelope]:
        """Load a hash-verified snapshot whose request parameters match.

        This provides a content-addressed resume point without treating a
        partially downloaded dataset as published. Corrupt cache entries fail
        closed instead of silently triggering another network request.
        """
        validate_safe_identifier(dataset_name, "dataset_name")
        dataset_dir = self.base_dir / dataset_name
        if not dataset_dir.exists():
            return None
        for meta_file in sorted(dataset_dir.glob("*.meta.json"), reverse=True):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Corrupt raw snapshot metadata: {meta_file}") from exc
            params = meta.get("params")
            if not isinstance(params, dict) or any(
                params.get(key) != value for key, value in required_params.items()
            ):
                continue
            content_hash = str(meta.get("content_hash", ""))
            raw_file = dataset_dir / f"{content_hash}.raw"
            if not raw_file.is_file():
                raise ValueError(f"Raw snapshot payload missing: {raw_file}")
            raw_bytes = raw_file.read_bytes()
            if hashlib.sha256(raw_bytes).hexdigest() != content_hash:
                raise ValueError(f"Raw snapshot hash mismatch: {raw_file}")
            return RawResponseEnvelope(
                provider_name=str(meta.get("provider_name", "")),
                endpoint=str(meta.get("endpoint", "")),
                params=params,
                retrieved_at=str(meta.get("retrieved_at", "")),
                status_code=int(meta.get("status_code", 0)),
                raw_body_bytes=raw_bytes,
                content_hash=content_hash,
            )
        return None

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

        # Byte-for-byte immutability & sidecar metadata corruption verification
        if raw_file.exists() and meta_file.exists():
            existing_bytes = raw_file.read_bytes()
            existing_hash = hashlib.sha256(existing_bytes).hexdigest()
            if existing_hash == content_hash:
                try:
                    meta_content = json.loads(meta_file.read_text(encoding="utf-8"))
                    if meta_content.get("content_hash") == content_hash:
                        # Content and metadata match perfectly: skip re-writing
                        return content_hash, raw_file
                except Exception:
                    pass  # Metadata corrupted or missing key, proceed to re-write

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
