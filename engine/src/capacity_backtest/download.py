"""Immutable, source-specific download snapshots."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .contracts import ArtifactManifest, SourceDefinition
from .storage import atomic_write


@dataclass(frozen=True)
class FetchResult:
    status: str
    manifest_path: Path | None
    artifact_path: Path | None
    error: str | None = None


def _filename(source: SourceDefinition, response: httpx.Response) -> str:
    candidate = Path(urlparse(str(response.url)).path).name
    if candidate and "." in candidate:
        return candidate
    extension = mimetypes.guess_extension(response.headers.get("content-type", "").split(";")[0])
    return f"{source.id}{extension or '.bin'}"


def _looks_like_error_page(source: SourceDefinition, response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    prefix = response.content[:256].lstrip().lower()
    expects_binary = source.format in {"xlsx", "xls", "csv", "pdf", "zip"}
    return expects_binary and ("text/html" in content_type or prefix.startswith(b"<!doctype html"))


def fetch_source(
    source: SourceDefinition,
    raw_root: Path,
    *,
    client: httpx.Client | None = None,
    retrieved_at: datetime | None = None,
) -> FetchResult:
    if not source.enabled:
        return FetchResult("disabled", None, None, source.disabled_reason)
    own_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        response = http.get(source.url, headers={"User-Agent": "GridPulseCapacityBacktest/0.1"})
        response.raise_for_status()
        if _looks_like_error_page(source, response):
            raise ValueError("received an HTML error page for a binary source")
        timestamp = retrieved_at or datetime.now(timezone.utc)
        digest = hashlib.sha256(response.content).hexdigest()
        directory = (
            raw_root
            / source.publisher.lower().replace(" ", "-")
            / source.id
            / timestamp.date().isoformat()
            / digest[:12]
        )
        directory.mkdir(parents=True, exist_ok=True)
        artifact_path = directory / _filename(source, response)
        if artifact_path.exists() and artifact_path.read_bytes() != response.content:
            raise ValueError("immutable snapshot collision")
        atomic_write(artifact_path, response.content)
        manifest = ArtifactManifest(
            source_id=source.id,
            source_url=source.url,
            retrieved_at=timestamp.isoformat(),
            sha256=digest,
            byte_length=len(response.content),
            content_type=response.headers.get("content-type", "unknown"),
            original_filename=artifact_path.name,
            http_status=response.status_code,
            truth_class=source.truth_class,
            limitations=[f"Must not be used for {item}." for item in source.prohibited_uses],
        )
        manifest_path = directory / "manifest.json"
        atomic_write(
            manifest_path,
            (json.dumps(manifest.as_dict(), indent=2, ensure_ascii=False) + "\n").encode(),
        )
        return FetchResult("succeeded", manifest_path, artifact_path)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return FetchResult("failed", None, None, str(exc))
    finally:
        if own_client:
            http.close()


def verify_snapshot(manifest_path: Path) -> bool:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    original_filename = manifest.get("original_filename")
    if original_filename:
        artifact = manifest_path.parent / str(original_filename)
    else:
        candidates = [
            path
            for path in manifest_path.parent.iterdir()
            if path.is_file() and path.name != manifest_path.name
        ]
        if len(candidates) != 1:
            return False
        artifact = candidates[0]
    if not artifact.is_file():
        return False
    return hashlib.sha256(artifact.read_bytes()).hexdigest() == expected
