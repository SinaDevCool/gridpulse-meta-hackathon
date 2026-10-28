"""Resolve and verify durable Microsoft OneDrive and volatile working storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DURABLE_DIRECTORIES = (
    "raw",
    "manifests",
    "normalized",
    "derived",
    "features",
    "targets",
    "models",
    "predictions",
    "simulations",
    "exports",
    "quality",
    "quarantine",
    "runs",
    "reports",
    "site-portfolios",
    "operator-confidential",
    "telemetry",
    "backups",
)
WORK_DIRECTORIES = (
    "cache",
    "staging",
    "tmp",
    "neo4j-data",
    "model-runs",
    "api-cache",
    "logs",
    "locks",
)
STORAGE_IDENTITY = ".gridpulse-storage.json"


class StorageSafetyError(ValueError):
    """Raised when a configured storage boundary is unsafe or ambiguous."""


@dataclass(frozen=True)
class StorageLayout:
    project_root: Path
    data_root: Path
    work_root: Path
    provider: str
    cloud_root: Path | None

    def as_dict(self) -> dict[str, str | None]:
        value = asdict(self)
        return {key: str(item) if isinstance(item, Path) else item for key, item in value.items()}


@dataclass(frozen=True)
class StoredSnapshot:
    """A content-addressed payload and its immutable retrieval observation."""

    blob_path: Path
    manifest_path: Path
    sha256: str
    byte_length: int
    blob_reused: bool


class SnapshotStore:
    """Store payload bytes once while preserving every source retrieval observation."""

    def __init__(self, layout: StorageLayout | Path) -> None:
        if isinstance(layout, StorageLayout):
            validate_storage(layout)
            self.data_root = layout.data_root
        else:
            self.data_root = layout.resolve()

    def capture(
        self,
        *,
        source_id: str,
        publisher: str,
        source_url: str,
        content: bytes,
        extension: str,
        retrieved_at: datetime,
        request: Mapping[str, object] | None = None,
        response_headers: Mapping[str, str] | None = None,
        status: str = "success_with_records",
        truth_class: str = "operator_published",
        geographic_resolution: str = "unknown",
        licence: str = "unconfirmed",
        limitations: tuple[str, ...] = (),
        adapter_version: str = "unknown",
    ) -> StoredSnapshot:
        digest = hashlib.sha256(content).hexdigest()
        suffix = extension.lstrip(".") or "bin"
        blob = self.data_root / "raw" / "blobs" / "sha256" / digest[:2] / f"{digest}.{suffix}"
        blob_reused = blob.exists()
        if blob_reused:
            if hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                raise OSError("content-addressed blob hash collision")
        else:
            atomic_write(blob, content)
            if hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                raise OSError("content-addressed blob verification failed")

        request_payload = dict(request or {})
        request_hash = hashlib.sha256(
            json.dumps(request_payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        stamp = retrieved_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%S.%fZ")
        manifest = (
            self.data_root
            / "manifests"
            / "captures"
            / source_id
            / retrieved_at.astimezone(timezone.utc).strftime("%Y/%m")
            / f"{stamp}-{request_hash[:12]}.json"
        )
        if manifest.exists():
            existing = json.loads(manifest.read_text(encoding="utf-8"))
            if existing.get("sha256") == digest and self.verify(manifest):
                return StoredSnapshot(blob, manifest, digest, len(content), True)
            raise FileExistsError(f"capture observation collision: {manifest}")
        payload = {
            "schema_version": "snapshot-manifest-v2",
            "source_id": source_id,
            "publisher": publisher,
            "source_url": source_url,
            "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
            "request": request_payload,
            "request_hash": request_hash,
            "response_headers": dict(response_headers or {}),
            "status": status,
            "sha256": digest,
            "byte_length": len(content),
            "blob_path": str(blob.relative_to(self.data_root)),
            "blob_reused": blob_reused,
            "adapter_version": adapter_version,
            "truth_class": truth_class,
            "geographic_resolution": geographic_resolution,
            "licence": licence,
            "limitations": list(limitations),
        }
        atomic_write(manifest, (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode())
        return StoredSnapshot(blob, manifest, digest, len(content), blob_reused)

    def verify(self, manifest_path: Path) -> bool:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "snapshot-manifest-v2":
            return False
        blob = self.data_root / str(manifest["blob_path"])
        if not blob.is_file() or blob.stat().st_size != manifest.get("byte_length"):
            return False
        return file_sha256(blob) == manifest.get("sha256")

    def capture_file(
        self,
        source: Path,
        *,
        source_id: str,
        publisher: str,
        source_url: str,
        retrieved_at: datetime,
        request: Mapping[str, object] | None = None,
        response_headers: Mapping[str, str] | None = None,
        truth_class: str = "operator_published",
        geographic_resolution: str = "unknown",
        licence: str = "unconfirmed",
        limitations: tuple[str, ...] = (),
        adapter_version: str = "unknown",
    ) -> StoredSnapshot:
        """Promote a large staged file without loading it into memory."""
        digest = file_sha256(source)
        suffix = source.suffix.lstrip(".") or "bin"
        blob = self.data_root / "raw" / "blobs" / "sha256" / digest[:2] / f"{digest}.{suffix}"
        reused = blob.exists()
        if reused:
            if file_sha256(blob) != digest:
                raise OSError("content-addressed blob hash collision")
        else:
            verified_copy(source, blob, expected_digest=digest)
        request_payload = dict(request or {})
        request_hash = hashlib.sha256(
            json.dumps(request_payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        stamp = retrieved_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%S.%fZ")
        manifest = (
            self.data_root / "manifests" / "captures" / source_id
            / retrieved_at.astimezone(timezone.utc).strftime("%Y/%m")
            / f"{stamp}-{request_hash[:12]}.json"
        )
        payload = {
            "schema_version": "snapshot-manifest-v2",
            "source_id": source_id,
            "publisher": publisher,
            "source_url": source_url,
            "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
            "request": request_payload,
            "request_hash": request_hash,
            "response_headers": dict(response_headers or {}),
            "status": "success_with_records",
            "sha256": digest,
            "byte_length": source.stat().st_size,
            "blob_path": str(blob.relative_to(self.data_root)),
            "blob_reused": reused,
            "adapter_version": adapter_version,
            "truth_class": truth_class,
            "geographic_resolution": geographic_resolution,
            "licence": licence,
            "limitations": list(limitations),
        }
        if manifest.exists():
            existing = json.loads(manifest.read_text(encoding="utf-8"))
            if existing.get("sha256") == digest and self.verify(manifest):
                return StoredSnapshot(blob, manifest, digest, source.stat().st_size, True)
            raise FileExistsError(f"capture observation collision: {manifest}")
        atomic_write(manifest, (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode())
        return StoredSnapshot(blob, manifest, digest, source.stat().st_size, reused)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _onedrive_root() -> Path | None:
    for name in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
        value = os.environ.get(name)
        if value:
            return Path(value).resolve()
    return None


def resolve_storage(project_root: Path) -> StorageLayout:
    """Resolve storage, preferring a dedicated OneDrive research-data directory."""
    root = project_root.resolve()
    cloud_root = _onedrive_root()
    configured = os.environ.get("GRIDPULSE_DATA_ROOT")
    if configured:
        data_root = Path(configured).resolve()
    elif cloud_root:
        data_root = cloud_root / "GridPulse Capacity Research Data"
    else:
        data_root = root / "data"
    default_work_root = Path.home() / "Documents" / "GridPulse-Capacity-Work"
    work_root = Path(os.environ.get("GRIDPULSE_WORK_ROOT", default_work_root)).resolve()
    provider = (
        "onedrive_filesystem" if cloud_root and _is_within(data_root, cloud_root) else "local"
    )
    return StorageLayout(root, data_root, work_root, provider, cloud_root)


def validate_storage(layout: StorageLayout, *, require_cloud: bool = False) -> None:
    """Fail closed for overlapping, repository-root, or non-cloud durable storage."""
    if layout.data_root == layout.project_root:
        raise StorageSafetyError("durable data root cannot be the repository root")
    if layout.data_root == layout.work_root:
        raise StorageSafetyError("durable and volatile roots must be different")
    if _is_within(layout.work_root, layout.data_root) or _is_within(
        layout.data_root, layout.work_root
    ):
        raise StorageSafetyError("durable and volatile roots must not overlap")
    if require_cloud and layout.provider != "onedrive_filesystem":
        raise StorageSafetyError("durable storage is not inside a detected Microsoft OneDrive root")


def atomic_write(destination: Path, content: bytes) -> None:
    """Write and atomically replace a completed file in its destination directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def initialise_storage(layout: StorageLayout, *, require_cloud: bool = False) -> None:
    """Create the layout and a non-secret identity record without replacing data."""
    validate_storage(layout, require_cloud=require_cloud)
    for name in DURABLE_DIRECTORIES:
        (layout.data_root / name).mkdir(parents=True, exist_ok=True)
    for name in WORK_DIRECTORIES:
        (layout.work_root / name).mkdir(parents=True, exist_ok=True)
    identity = layout.data_root / STORAGE_IDENTITY
    payload = {
        "schema_version": "gridpulse-storage-v2",
        "provider": layout.provider,
        "created_or_verified_at": datetime.now(timezone.utc).isoformat(),
        "immutable_raw": True,
        "volatile_work_separate": True,
    }
    if identity.exists():
        previous = json.loads(identity.read_text(encoding="utf-8"))
        if previous.get("schema_version") != payload["schema_version"]:
            raise StorageSafetyError("unrecognized storage identity schema")
    atomic_write(identity, json.dumps(payload, indent=2).encode() + b"\n")


def file_sha256(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_copy(source: Path, destination: Path, *, expected_digest: str | None = None) -> str:
    """Copy to durable storage atomically and verify its SHA-256 after the copy."""
    digest = expected_digest or file_sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copyfile(source, temporary)
        if file_sha256(temporary) != digest:
            raise OSError("durable copy hash verification failed")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def storage_health(layout: StorageLayout, *, require_cloud: bool = False) -> dict[str, object]:
    """Return a machine-readable, write-tested storage health report."""
    initialise_storage(layout, require_cloud=require_cloud)
    probe = layout.data_root / "manifests" / ".write-probe"
    content = b"gridpulse-storage-probe\n"
    atomic_write(probe, content)
    write_verified = probe.read_bytes() == content
    probe.unlink(missing_ok=True)
    usage = shutil.disk_usage(layout.data_root)
    return {
        **layout.as_dict(),
        "status": "healthy" if write_verified else "failed",
        "write_verified": write_verified,
        "free_bytes": usage.free,
        "durable_directories": list(DURABLE_DIRECTORIES),
        "work_directories": list(WORK_DIRECTORIES),
    }


def storage_inventory(layout: StorageLayout) -> dict[str, object]:
    """Inventory durable files without interpreting their contents."""
    validate_storage(layout)
    totals: dict[str, dict[str, int]] = {}
    for name in DURABLE_DIRECTORIES:
        directory = layout.data_root / name
        files = (
            [path for path in directory.rglob("*") if path.is_file()] if directory.exists() else []
        )
        totals[name] = {"files": len(files), "bytes": sum(path.stat().st_size for path in files)}
    return {"provider": layout.provider, "data_root": str(layout.data_root), "directories": totals}


def captured_blobs(data_root: Path, source_id: str) -> list[tuple[Path, dict[str, object]]]:
    """Return verified v2 payloads for one source in retrieval order."""
    results: list[tuple[Path, dict[str, object]]] = []
    root = data_root / "manifests" / "captures" / source_id
    for manifest_path in sorted(root.rglob("*.json")) if root.exists() else []:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        blob = data_root / str(manifest["blob_path"])
        if (
            not blob.is_file()
            or file_sha256(blob) != manifest["sha256"]
        ):
            raise OSError(f"capture blob failed verification: {manifest_path}")
        results.append((blob, manifest))
    return results


def migrate_legacy_data(layout: StorageLayout) -> dict[str, object]:
    """Copy legacy repository raw payloads into the cloud store without deleting originals."""
    initialise_storage(layout, require_cloud=True)
    legacy_root = layout.project_root / "data" / "raw"
    store = SnapshotStore(layout)
    migrated = reused = bytes_seen = 0
    failures: list[dict[str, str]] = []
    for path in sorted(item for item in legacy_root.rglob("*") if item.is_file()):
        if path.name in {".gitkeep", "manifest.json"}:
            continue
        relative = path.relative_to(legacy_root)
        source_id = relative.parts[0] if len(relative.parts) > 1 else path.stem
        sidecar = path.parent / "manifest.json"
        prior: dict[str, object] = {}
        if sidecar.is_file():
            try:
                prior = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                prior = {"legacy_manifest_unreadable": True}
        raw_time = prior.get("retrieved_at")
        try:
            retrieved_at = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            retrieved_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
        try:
            stored = store.capture(
                source_id=f"legacy-{source_id}",
                publisher=str(prior.get("publisher") or prior.get("source") or "legacy capture"),
                source_url=str(prior.get("url") or "unknown"),
                content=path.read_bytes(),
                extension=path.suffix or ".bin",
                retrieved_at=retrieved_at,
                request={
                    "legacy_path": str(relative).replace("\\", "/"),
                    "legacy_manifest": prior,
                },
                truth_class=str(prior.get("truth_class") or "unknown"),
                geographic_resolution="legacy_manifest_dependent",
                limitations=(
                    "Migrated without deleting the original repository-local payload.",
                    "Legacy retrieval semantics are retained in request.legacy_manifest.",
                ),
                adapter_version="legacy-migration-v1",
            )
            migrated += 1
            reused += int(stored.blob_reused)
            bytes_seen += stored.byte_length
        except (OSError, ValueError, FileExistsError) as exc:
            failures.append({"path": str(path), "error": str(exc)})
    return {
        "schema_version": "legacy-migration-report-v1",
        "legacy_root": str(legacy_root),
        "data_root": str(layout.data_root),
        "migrated_payloads": migrated,
        "reused_blobs": reused,
        "logical_bytes": bytes_seen,
        "failures": failures,
        "originals_deleted": False,
        "status": "succeeded" if not failures else "partial",
    }


def compact_legacy_cloud_snapshots(layout: StorageLayout) -> dict[str, object]:
    """Replace verified v1 cloud snapshot copies with v2 manifests and shared blobs."""
    validate_storage(layout, require_cloud=True)
    raw_root = layout.data_root / "raw"
    blob_root = raw_root / "blobs"
    store = SnapshotStore(layout)
    migrated = removed_files = removed_bytes = 0
    failures = []
    manifests = [
        path for path in raw_root.rglob("manifest.json") if not _is_within(path, blob_root)
    ]
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            relative = manifest.get("storage_path")
            if not relative:
                raise ValueError("legacy manifest lacks storage_path")
            artifact = layout.data_root / str(relative)
            if not _is_within(artifact, raw_root) or _is_within(artifact, blob_root):
                raise StorageSafetyError("legacy artifact is outside the compactable raw boundary")
            content = artifact.read_bytes()
            expected = str(manifest.get("sha256", ""))
            if hashlib.sha256(content).hexdigest() != expected:
                raise OSError("legacy artifact hash mismatch")
            retrieved_at = datetime.fromisoformat(
                str(manifest["retrieved_at"]).replace("Z", "+00:00")
            )
            stored = store.capture(
                source_id=str(manifest["source_id"]),
                publisher=str(manifest.get("publisher", "unknown")),
                source_url=str(manifest.get("source_url", "unknown")),
                content=content,
                extension=artifact.suffix,
                retrieved_at=retrieved_at,
                request={"legacy_v1_manifest": manifest},
                response_headers=manifest.get("response_headers", {}),
                truth_class=str(manifest.get("truth_class", "unknown")),
                geographic_resolution=str(manifest.get("geographic_resolution", "unknown")),
                licence=str(manifest.get("licence", "unconfirmed")),
                limitations=tuple(manifest.get("limitations", [])),
                adapter_version="v1-cloud-compaction-v1",
            )
            if not store.verify(stored.manifest_path):
                raise OSError("replacement v2 capture failed verification")
            for target in (artifact, manifest_path):
                size = target.stat().st_size
                target.unlink()
                removed_files += 1
                removed_bytes += size
            migrated += 1
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            failures.append({"manifest": str(manifest_path), "error": str(exc)})
    for directory in sorted(
        (path for path in raw_root.rglob("*") if path.is_dir() and not _is_within(path, blob_root)),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {
        "schema_version": "cloud-v1-compaction-report-v1",
        "migrated_snapshots": migrated,
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "failures": failures,
        "replacement": "content-addressed blobs plus snapshot-manifest-v2 captures",
        "recoverable": True,
        "status": "succeeded" if not failures else "partial",
    }
