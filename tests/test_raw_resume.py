"""Tests for content-addressed raw snapshot resume."""

from pathlib import Path

import pytest

from qmo.providers.protocols import RawResponseEnvelope
from qmo.storage.raw_store import RawSnapshotStore


def envelope() -> RawResponseEnvelope:
    return RawResponseEnvelope(
        provider_name="finmind",
        endpoint="https://example.test/data",
        params={
            "dataset": "TaiwanStockPrice",
            "data_id": "2330",
            "start_date": "2026-09-28",
            "end_date": "2026-09-28",
        },
        status_code=200,
        raw_body_bytes=b'{"data": []}',
    )


def test_load_matching_returns_verified_envelope(tmp_path: Path) -> None:
    store = RawSnapshotStore(tmp_path)
    original = envelope()
    store.save(original, "daily_price")
    loaded = store.load_matching(
        "daily_price",
        {"data_id": "2330", "start_date": "2026-09-28", "end_date": "2026-09-28"},
    )
    assert loaded is not None
    assert loaded.content_hash == original.content_hash
    assert loaded.raw_body_bytes == original.raw_body_bytes


def test_load_matching_returns_none_for_different_request(tmp_path: Path) -> None:
    store = RawSnapshotStore(tmp_path)
    store.save(envelope(), "daily_price")
    assert store.load_matching("daily_price", {"data_id": "2317"}) is None


def test_load_matching_fails_closed_on_tampering(tmp_path: Path) -> None:
    store = RawSnapshotStore(tmp_path)
    _, raw_path = store.save(envelope(), "daily_price")
    raw_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        store.load_matching("daily_price", {"data_id": "2330"})
