import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from capacity_backtest.download import verify_snapshot
from capacity_backtest.storage import (
    DURABLE_DIRECTORIES,
    WORK_DIRECTORIES,
    SnapshotStore,
    StorageLayout,
    StorageSafetyError,
    compact_legacy_cloud_snapshots,
    initialise_storage,
    migrate_legacy_data,
    resolve_storage,
    storage_health,
    storage_inventory,
    validate_storage,
)


def test_source_specific_single_artifact_manifest_verifies(tmp_path: Path) -> None:
    artifact = tmp_path / "response.xml"
    artifact.write_bytes(b"source response")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}))
    assert verify_snapshot(manifest)
    (tmp_path / "unexpected.bin").write_bytes(b"ambiguous")
    assert verify_snapshot(manifest) is False


def test_storage_defaults_to_repository_and_creates_layout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GRIDPULSE_DATA_ROOT", raising=False)
    monkeypatch.delenv("GRIDPULSE_WORK_ROOT", raising=False)
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    layout = resolve_storage(tmp_path)
    initialise_storage(layout)
    assert layout.data_root == tmp_path.resolve() / "data"
    assert layout.work_root == (Path.home() / "Documents" / "GridPulse-Capacity-Work").resolve()
    assert all((layout.data_root / name).is_dir() for name in DURABLE_DIRECTORIES)
    assert all((layout.work_root / name).is_dir() for name in WORK_DIRECTORIES)


def test_storage_honours_environment_overrides(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "cloud-data"
    work_root = tmp_path / "local-work"
    monkeypatch.setenv("GRIDPULSE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("GRIDPULSE_WORK_ROOT", str(work_root))
    layout = resolve_storage(tmp_path / "project")
    assert layout.data_root == data_root.resolve()
    assert layout.work_root == work_root.resolve()


def test_storage_prefers_dedicated_onedrive_root(tmp_path: Path, monkeypatch) -> None:
    cloud = tmp_path / "OneDrive"
    monkeypatch.delenv("GRIDPULSE_DATA_ROOT", raising=False)
    monkeypatch.setenv("OneDrive", str(cloud))
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    layout = resolve_storage(tmp_path / "project")
    assert layout.provider == "onedrive_filesystem"
    assert layout.data_root == cloud / "GridPulse Capacity Research Data"
    assert storage_health(layout, require_cloud=True)["status"] == "healthy"
    assert storage_inventory(layout)["directories"]["raw"] == {"files": 0, "bytes": 0}


def test_storage_rejects_unsafe_boundaries(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path, tmp_path, tmp_path / "work", "local", None)
    with pytest.raises(StorageSafetyError, match="repository root"):
        validate_storage(layout)


def test_snapshot_store_reuses_payload_but_preserves_capture_history(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "cloud")
    first = store.capture(
        source_id="source",
        publisher="Publisher",
        source_url="https://example.test/data",
        content=b"same immutable response",
        extension="csv",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = store.capture(
        source_id="source",
        publisher="Publisher",
        source_url="https://example.test/data",
        content=b"same immutable response",
        extension="csv",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=1),
    )
    assert first.blob_path == second.blob_path
    assert first.blob_reused is False
    assert second.blob_reused is True
    assert first.manifest_path != second.manifest_path
    assert store.verify(first.manifest_path)
    assert store.verify(second.manifest_path)


def test_legacy_migration_is_idempotent_and_preserves_original(tmp_path: Path) -> None:
    project = tmp_path / "project"
    legacy = project / "data" / "raw" / "entsoe-live" / "2025" / "A65" / "capture"
    legacy.mkdir(parents=True)
    original = legacy / "response.xml"
    original.write_bytes(b"document")
    (legacy / "manifest.json").write_text(
        json.dumps(
            {
                "publisher": "ENTSO-E",
                "url": "https://example.test/api",
                "retrieved_at": "2026-01-01T00:00:00+00:00",
            }
        )
    )
    layout = StorageLayout(
        project,
        tmp_path / "OneDrive" / "data",
        tmp_path / "work",
        "onedrive_filesystem",
        tmp_path / "OneDrive",
    )
    first = migrate_legacy_data(layout)
    second = migrate_legacy_data(layout)
    assert first["migrated_payloads"] == second["migrated_payloads"] == 1
    assert second["reused_blobs"] == 1
    assert original.read_bytes() == b"document"
    assert first["originals_deleted"] is False


def test_cloud_compaction_removes_only_verified_redundant_v1_copy(tmp_path: Path) -> None:
    cloud = tmp_path / "OneDrive" / "data"
    work = tmp_path / "work"
    project = tmp_path / "project"
    layout = StorageLayout(project, cloud, work, "onedrive_filesystem", tmp_path / "OneDrive")
    initialise_storage(layout, require_cloud=True)
    directory = cloud / "raw" / "publisher" / "source" / "capture"
    directory.mkdir(parents=True)
    artifact = directory / "response.csv"
    artifact.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "regional-snapshot-manifest-v1",
                "source_id": "source",
                "publisher": "Publisher",
                "source_url": "https://example.test",
                "retrieved_at": "2026-01-01T00:00:00+00:00",
                "sha256": digest,
                "byte_length": 7,
                "storage_path": str(artifact.relative_to(cloud)),
            }
        )
    )
    report = compact_legacy_cloud_snapshots(layout)
    assert report["status"] == "succeeded"
    assert report["migrated_snapshots"] == 1
    assert not artifact.exists()
    captures = list((cloud / "manifests" / "captures" / "source").rglob("*.json"))
    assert len(captures) == 1
    assert SnapshotStore(layout).verify(captures[0])
