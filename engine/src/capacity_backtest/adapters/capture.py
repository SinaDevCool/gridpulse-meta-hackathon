"""Immutable capture wrapper for every read-only external adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from capacity_backtest.storage import SnapshotStore


@dataclass(frozen=True)
class AdapterCapture:
    source_id: str
    payload_sha256: str
    manifest_path: str
    transport_mode: str = "read_only"
    command_capable: bool = False


def capture_read_only_payload(
    store: SnapshotStore,
    *,
    source_id: str,
    publisher: str,
    source_url: str,
    content: bytes,
    extension: str,
    retrieved_at: datetime,
    truth_class: str,
    licence: str,
    adapter_version: str,
) -> AdapterCapture:
    stored = store.capture(
        source_id=source_id, publisher=publisher, source_url=source_url,
        content=content, extension=extension, retrieved_at=retrieved_at,
        truth_class=truth_class, licence=licence, adapter_version=adapter_version,
        limitations=("Read-only capture; no command or mutation capability.",),
    )
    return AdapterCapture(source_id, stored.sha256, str(stored.manifest_path))
