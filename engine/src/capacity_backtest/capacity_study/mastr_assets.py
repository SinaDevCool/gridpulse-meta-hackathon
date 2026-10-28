"""Streaming normalization of public MaStR XML asset extracts."""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import iterparse

import httpx

from capacity_backtest.storage import SnapshotStore, atomic_write, file_sha256

SOURCE_ID = "bnetza-mastr-full-export"
SOURCE_URL_2025 = (
    "https://download.marktstammdatenregister.de/Stichtag/"
    "Gesamtdatenexport_20250101_24.2.zip"
)
LICENCE = "Datenlizenz Deutschland – Namensnennung – Version 2.0"
CHUNK_SIZE = 8 * 1024 * 1024
EXPECTED_XML_FAMILIES = ("Einheiten", "Marktakteure", "Lokationen")

FIELDS = {
    "EinheitMastrNummer",
    "LokationMastrNummer",
    "NetzbetreiberMastrNummer",
    "Gemeindeschluessel",
    "Postleitzahl",
    "Inbetriebnahmedatum",
    "EinheitSystemstatus",
    "Bruttoleistung",
    "Nettonennleistung",
    "Laengengrad",
    "Breitengrad",
}


class DownloadLockError(RuntimeError):
    """Raised when another live process owns the fixed-snapshot download."""


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # ``os.kill(pid, 0)`` is not a harmless existence probe on Windows:
        # CPython delegates it to TerminateProcess and can kill the lock owner.
        # Query a synchronisation handle instead, without signalling the process.
        import ctypes

        synchronize = 0x00100000
        still_active = 0x00000102
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_lock(lock_path: Path, payload: dict[str, object]) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            prior = json.loads(lock_path.read_text(encoding="utf-8"))
            prior_pid = int(prior.get("pid", -1))
        except (OSError, ValueError, json.JSONDecodeError):
            prior_pid = -1
        if _process_alive(prior_pid):
            raise DownloadLockError(f"MaStR download is already owned by PID {prior_pid}")
        lock_path.unlink(missing_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(lock_path, flags)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        lock_path.unlink(missing_ok=True)
        raise


def _checkpoint_path(staging: Path) -> Path:
    return staging.with_suffix(".checkpoint.json")


def _write_checkpoint(
    staging: Path,
    *,
    source_url: str,
    snapshot_date: str,
    expected_size: int,
    etag: str,
    last_modified: str,
) -> None:
    atomic_write(
        _checkpoint_path(staging),
        (
            json.dumps(
                {
                    "schema_version": "gridpulse-download-checkpoint-v1",
                    "source_url": source_url,
                    "snapshot_date": snapshot_date,
                    "expected_size": expected_size,
                    "etag": etag,
                    "last_modified": last_modified,
                    "downloaded_bytes": staging.stat().st_size if staging.exists() else 0,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "chunk_size_bytes": CHUNK_SIZE,
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )


def _validate_checkpoint(
    staging: Path,
    *,
    source_url: str,
    snapshot_date: str,
    expected_size: int,
    etag: str,
    last_modified: str,
) -> None:
    checkpoint = _checkpoint_path(staging)
    if not staging.exists() and checkpoint.exists():
        checkpoint.unlink()
    if not staging.exists() or not checkpoint.exists():
        return
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    expected = {
        "source_url": source_url,
        "snapshot_date": snapshot_date,
        "expected_size": expected_size,
        "etag": etag,
        "last_modified": last_modified,
        "downloaded_bytes": staging.stat().st_size,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("MaStR checkpoint does not match the fixed remote object")


def _zip_inventory(path: Path) -> list[dict[str, object]]:
    inventory = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("MaStR archive contains duplicate member names")
        for info in archive.infolist():
            member_path = Path(info.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError("MaStR archive contains an unsafe member path")
            if info.flag_bits & 0x1:
                raise ValueError("MaStR archive contains an encrypted member")
            inventory.append(
                {
                    "name": info.filename,
                    "bytes": info.file_size,
                    "compressed_bytes": info.compress_size,
                    "crc": info.CRC,
                }
            )
        failed = archive.testzip()
        if failed:
            raise ValueError(f"MaStR archive CRC validation failed for {failed}")
    if not any(str(item["name"]).lower().endswith(".xml") for item in inventory):
        raise ValueError("MaStR archive contains no XML members")
    member_names = " ".join(str(item["name"]) for item in inventory).lower()
    missing = [family for family in EXPECTED_XML_FAMILIES if family.lower() not in member_names]
    if missing:
        raise ValueError(f"MaStR archive is missing expected XML families: {missing}")
    return inventory


def _download_once(
    staging: Path,
    *,
    source_url: str,
    snapshot_date: str,
    expected_size: int,
    etag: str,
    last_modified: str,
) -> dict[str, str]:
    offset = staging.stat().st_size if staging.exists() else 0
    request_headers = {"Range": f"bytes={offset}-"} if offset else {}
    timeout = httpx.Timeout(connect=60, read=180, write=60, pool=60)
    with httpx.stream(
        "GET", source_url, headers=request_headers, follow_redirects=True, timeout=timeout
    ) as response:
        response.raise_for_status()
        if offset:
            content_range = response.headers.get("content-range", "")
            if response.status_code != 206 or not content_range.startswith(f"bytes {offset}-"):
                raise ValueError("MaStR server returned an unsafe resume response")
            if not content_range.endswith(f"/{expected_size}"):
                raise ValueError("MaStR resume response changed total byte length")
        elif response.status_code != 200:
            raise ValueError("MaStR initial download did not return HTTP 200")
        response_etag = response.headers.get("etag", "")
        if etag and response_etag and response_etag != etag:
            raise ValueError("MaStR ETag changed during download")
        with staging.open("ab" if offset else "wb") as stream:
            for chunk in response.iter_bytes(CHUNK_SIZE):
                if staging.stat().st_size + len(chunk) > expected_size:
                    raise ValueError("MaStR response exceeded declared byte length")
                stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
                _write_checkpoint(
                    staging,
                    source_url=source_url,
                    snapshot_date=snapshot_date,
                    expected_size=expected_size,
                    etag=etag,
                    last_modified=last_modified,
                )
        return dict(response.headers)


def capture_mastr_archive(
    data_root: Path,
    work_root: Path,
    *,
    source_url: str = SOURCE_URL_2025,
    snapshot_date: str = "2025-01-01",
) -> Path:
    """Stream a fixed MaStR release to staging, promote it, then remove staging."""
    staging = work_root / "staging" / f"mastr-{snapshot_date}.zip"
    staging.parent.mkdir(parents=True, exist_ok=True)
    lock_path = work_root / "locks" / f"mastr-{snapshot_date}.lock"
    _acquire_lock(
        lock_path,
        {
            "schema_version": "gridpulse-download-lock-v1",
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "process_started_at": datetime.now(timezone.utc).isoformat(),
            "source_url": source_url,
            "snapshot_date": snapshot_date,
            "staging_path": str(staging),
            "starting_byte_offset": staging.stat().st_size if staging.exists() else 0,
        },
    )
    headers: dict[str, str] = {}
    promoted = False
    try:
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            head = client.head(source_url)
            head.raise_for_status()
        expected_size = int(head.headers.get("content-length", "0"))
        etag = head.headers.get("etag", "")
        last_modified = head.headers.get("last-modified", "")
        if expected_size <= 0:
            raise ValueError("MaStR server did not provide a usable Content-Length")
        if staging.exists() and staging.stat().st_size > expected_size:
            raise ValueError("MaStR staged file exceeds fixed remote object length")
        _validate_checkpoint(
            staging,
            source_url=source_url,
            snapshot_date=snapshot_date,
            expected_size=expected_size,
            etag=etag,
            last_modified=last_modified,
        )
        _write_checkpoint(
            staging,
            source_url=source_url,
            snapshot_date=snapshot_date,
            expected_size=expected_size,
            etag=etag,
            last_modified=last_modified,
        )
        for attempt, delay in enumerate((0, 5, 15, 30, 60, 120), start=1):
            if staging.exists() and staging.stat().st_size == expected_size:
                break
            if delay:
                time.sleep(delay)
            try:
                headers = _download_once(
                    staging,
                    source_url=source_url,
                    snapshot_date=snapshot_date,
                    expected_size=expected_size,
                    etag=etag,
                    last_modified=last_modified,
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 6:
                    raise
        if staging.stat().st_size != expected_size:
            raise ValueError("MaStR staged byte length differs from Content-Length")
        inventory = _zip_inventory(staging)
        stored = SnapshotStore(data_root).capture_file(
            staging,
            source_id=SOURCE_ID,
            publisher="Bundesnetzagentur",
            source_url=source_url,
            retrieved_at=datetime.now(timezone.utc),
            request={"snapshot_date": snapshot_date},
            response_headers={
                **headers,
                "etag": etag,
                "last-modified": last_modified,
                "content-length": str(expected_size),
            },
            truth_class="authority_published_registry",
            geographic_resolution="registered public units and market actors",
            licence=LICENCE,
            limitations=(
                "Records may be unverified, incomplete, erroneous, or duplicated.",
                "Confidential fields are excluded from the public export.",
            ),
            adapter_version="mastr-full-export-v2",
        )
        inventory_path = data_root / "quality" / "mastr" / stored.sha256 / "member-inventory.json"
        atomic_write(
            inventory_path,
            (json.dumps({"source_sha256": stored.sha256, "members": inventory}, indent=2) + "\n").encode(),
        )
        promoted = True
        return stored.manifest_path
    finally:
        lock_path.unlink(missing_ok=True)
        if promoted:
            staging.unlink(missing_ok=True)
            _checkpoint_path(staging).unlink(missing_ok=True)


def normalize_mastr_archive(
    path: Path, data_root: Path, *, region_prefixes: tuple[str, ...] = ("10", "11", "12")
) -> Path:
    digest = file_sha256(path)
    destination = data_root / "normalized" / "mastr" / digest
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    handle, temporary_name = tempfile.mkstemp(prefix=".assets.", dir=destination)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            with zipfile.ZipFile(path) as archive:
                for member in archive.namelist():
                    if not member.lower().endswith(".xml"):
                        continue
                    with archive.open(member) as stream:
                        for _, element in iterparse(stream, events=("end",)):
                            values = {
                                child.tag.split("}")[-1]: child.text
                                for child in element
                                if child.tag.split("}")[-1] in FIELDS
                            }
                            postal = values.get("Postleitzahl") or ""
                            municipality = values.get("Gemeindeschluessel") or ""
                            if values.get("EinheitMastrNummer") and (
                                postal.startswith(region_prefixes)
                                or municipality.startswith(region_prefixes)
                            ):
                                values["source_member"] = member
                                output.write(json.dumps(values, ensure_ascii=False) + "\n")
                                count += 1
                            if values.get("EinheitMastrNummer"):
                                element.clear()
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination / "assets.jsonl")
    finally:
        temporary.unlink(missing_ok=True)
    atomic_write(
        destination / "manifest.json",
        (
            json.dumps(
                {
                    "schema_version": "gridpulse-mastr-assets-v1",
                    "source_sha256": digest,
                    "asset_count": count,
                    "region_prefixes": region_prefixes,
                    "truth_class": "operator_published",
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )
    return destination
