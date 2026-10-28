"""Immutable 50Hertz vertical-grid-load archive ingestion and profiling."""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .storage import SnapshotStore, atomic_write

LIST_URL = "https://ds.50hertz.com/api/WebPage50Hz/VertikaleNetzlastListDownloadFilesJsonp"
DOWNLOAD_URL = "https://ds.50hertz.com/api/WebPage50Hz/VertikaleNetzlastDownloadFile"


def parse_file_list(content: str) -> list[str]:
    payload = content[content.find("[") : content.rfind("]") + 1]
    files = json.loads(payload)
    if not isinstance(files, list) or any(not str(name).endswith(".csv") for name in files):
        raise ValueError("unexpected vertical-load file listing")
    return sorted({str(name) for name in files})


def profile_vertical_load(content: bytes, *, snapshot_hash: str) -> dict[str, object]:
    text = content.decode("utf-16")
    rows = []
    invalid_mw = 0
    for raw in csv.reader(io.StringIO(text), delimiter=";"):
        if len(raw) < 4 or raw[0] in {"", "Maximum", "Minimum", "Datum"}:
            continue
        try:
            local_start = datetime.strptime(f"{raw[0]} {raw[1]}", "%d.%m.%Y %H:%M").replace(
                tzinfo=ZoneInfo("Europe/Berlin")
            )
            value = int(raw[3]) if raw[3] not in {"", "n/a", "n.v."} else None
        except ValueError:
            invalid_mw += 1
            continue
        rows.append((local_start.isoformat(), value))
    timestamps = [item[0] for item in rows]
    duplicate_local_timestamps = len(timestamps) - len(set(timestamps))
    values = [item[1] for item in rows if item[1] is not None]
    first = min((datetime.fromisoformat(item) for item in timestamps), default=None)
    last = max((datetime.fromisoformat(item) for item in timestamps), default=None)
    complete_year = bool(
        first
        and last
        and first.month == first.day == 1
        and last.month == 12
        and last.day == 31
        and first.year == last.year
    )
    expected_complete_year = (
        (366 if calendar.isleap(first.year) else 365) * 96 if complete_year and first else None
    )
    return {
        "schema_version": "50hertz-vertical-load-quality-v1",
        "snapshot_hash": snapshot_hash,
        "record_count": len(rows),
        "coverage_start_local": min(timestamps) if timestamps else None,
        "coverage_end_local": max(timestamps) if timestamps else None,
        "missing_values": sum(item[1] is None for item in rows),
        "invalid_rows": invalid_mw,
        "duplicate_local_timestamps": duplicate_local_timestamps,
        "expected_complete_year_intervals": expected_complete_year,
        "missing_record_intervals": (
            max(0, expected_complete_year - len(rows))
            if expected_complete_year is not None
            else None
        ),
        "minimum_mw": min(values) if values else None,
        "maximum_mw": max(values) if values else None,
        "unit": "MW",
        "geographic_resolution": "50hertz_control_area",
        "timezone": "Europe/Berlin local labels without explicit UTC offset",
        "training_admitted": False,
        "capacity_claim": False,
        "warnings": [
            "Repeated autumn timestamps cannot be disambiguated without an offset or fold marker.",
            "Vertical grid load is control-area context, not distribution-node loading.",
            "Archive revision retention and reuse rights are not confirmed.",
        ],
    }


def capture_vertical_load_archive(data_root: Path) -> dict[str, object]:
    retrieved_at = datetime.now(timezone.utc)
    with httpx.Client(follow_redirects=True, timeout=90) as client:
        listing = client.get(LIST_URL)
        listing.raise_for_status()
        files = parse_file_list(listing.text)
        results = []
        for filename in files:
            response = client.get(DOWNLOAD_URL, params={"fileName": filename})
            response.raise_for_status()
            content = response.content
            stored = SnapshotStore(data_root).capture(
                source_id="fifty_hertz_vertical_grid_load_archive",
                publisher="50Hertz Transmission GmbH",
                source_url=str(response.url),
                content=content,
                extension="csv",
                retrieved_at=retrieved_at,
                request={"method": "GET", "fileName": filename},
                response_headers={
                    name: value
                    for name, value in response.headers.items()
                    if name.lower() in {"etag", "last-modified", "content-type"}
                },
                truth_class="operator_published_context",
                geographic_resolution="50hertz_control_area",
                licence="unconfirmed",
                adapter_version="50hertz-vertical-load-v1",
                limitations=(
                    "Control-area context only; no nodal capacity claim.",
                    "Local timestamps lack explicit offsets.",
                ),
            )
            quality = profile_vertical_load(content, snapshot_hash=stored.sha256)
            quality_path = (
                data_root
                / "quality"
                / "fifty_hertz_vertical_grid_load_archive"
                / f"{stored.sha256}.json"
            )
            atomic_write(quality_path, (json.dumps(quality, indent=2) + "\n").encode())
            results.append(
                {
                    "filename": filename,
                    "sha256": stored.sha256,
                    "bytes": stored.byte_length,
                    "quality": str(quality_path),
                    "reused_blob": stored.blob_reused,
                }
            )
    return {
        "schema_version": "50hertz-vertical-load-capture-v1",
        "retrieved_at": retrieved_at.isoformat(),
        "files": results,
        "file_count": len(results),
        "total_bytes": sum(item["bytes"] for item in results),
        "listing_sha256": hashlib.sha256(listing.content).hexdigest(),
        "capacity_claim": False,
    }
