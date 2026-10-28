"""Publication-aware capture and parsing of historical 50Hertz Redispatch 2.0 pages."""

from __future__ import annotations

import csv
import html
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .events import GeographicResolution, GridEvent
from .storage import SnapshotStore, atomic_write

SOURCE_ID = "fifty_hertz_redispatch_history"
PUBLISHER = "50Hertz Transmission GmbH"
BASE_URL = (
    "https://www.50hertz.com/de/Transparenz/Kennzahlen/Engpassmanagement/"
    "Ma%C3%9Fnahmennach13Abs1EnWGEEundAbrufebeimVNB"
)
CSV_URL = "https://www.50hertz.com/desktopmodules/remit-ma/api/export/de/9623/csv"
ADAPTER_VERSION = "fifty-hertz-history-v1"
BERLIN = ZoneInfo("Europe/Berlin")
RECORD = re.compile(
    r'<li\s+id="(Redispatch_(\d{14})_(\d{3}))"[^>]*>(.*?)</li>', re.DOTALL | re.IGNORECASE
)


@dataclass(frozen=True)
class HistoricalMeasure:
    record_id: str
    interval_start: datetime
    interval_end: datetime
    published_at: datetime
    revision: int
    increase_mw: float | None
    reduction_mw: float | None
    displayed_date: str
    displayed_interval: str
    publication_time_raw: str

    def events(
        self, *, retrieved_at: datetime, snapshot_hash: str, source_url: str
    ) -> list[GridEvent]:
        results = []
        for direction, power in (("up", self.increase_mw), ("down", self.reduction_mw)):
            results.append(
                GridEvent(
                    event_id=f"{self.interval_start.isoformat()}:{direction}",
                    published_at=self.published_at,
                    starts_at=self.interval_start,
                    ends_at=self.interval_end,
                    operator=PUBLISHER,
                    area="50Hertz control area",
                    kind="redispatch_2_control_area_aggregate",
                    direction=direction,
                    power_mw=power,
                    energy_mwh=None,
                    revision=self.revision,
                    source_id=SOURCE_ID,
                    source_record_id=f"{self.record_id}:{direction}",
                    retrieved_at=retrieved_at,
                    bidding_zone="DE-LU",
                    control_area="10YDE-VE-------2",
                    affected_geography="50Hertz control area",
                    geographic_resolution=GeographicResolution.CONTROL_AREA,
                    source_url=source_url,
                    snapshot_hash=snapshot_hash,
                    validation_warnings=(
                        "Control-area aggregate; not a Berlin or Brandenburg node measurement.",
                        "Generation timestamp is treated as publication availability and must be audited.",
                    ),
                )
            )
        return results


def _plain(fragment: str) -> str:
    value = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(html.unescape(value).split())


def _class_text(body: str, class_name: str) -> str:
    match = re.search(
        rf'<div\s+class="[^"]*{re.escape(class_name)}[^"]*">(.*?)</div>\s*</div>',
        body,
        re.DOTALL | re.IGNORECASE,
    )
    return _plain(match.group(1)) if match else ""


def _value(body: str, label: str) -> float | None:
    match = re.search(
        rf"<label>\s*{re.escape(label)}\s*</label>.*?<span[^>]*>\s*([^<]+?)\s*</span>",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    raw = html.unescape(match.group(1)).strip().replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _local_publication(value: str) -> datetime:
    naive = datetime.strptime(value, "%d.%m.%Y %H:%M")  # noqa: DTZ007
    first = naive.replace(tzinfo=BERLIN, fold=0)
    second = naive.replace(tzinfo=BERLIN, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError(f"ambiguous Europe/Berlin publication time: {value}")
    return first.astimezone(timezone.utc)


def parse_history_page(content: bytes) -> tuple[list[HistoricalMeasure], list[str]]:
    text = content.decode("utf-8")
    records: list[HistoricalMeasure] = []
    warnings: list[str] = []
    for match in RECORD.finditer(text):
        record_id, stamp, revision_raw, body = match.groups()
        displayed_date = _class_text(body, "rma-data-timeslot-date").removeprefix("Datum ")
        displayed_interval = _class_text(body, "rma-data-timeslot-time").removeprefix("von - bis ")
        publication_raw = _class_text(body, "rma-data-timeslot-creationdate").removeprefix(
            "Erzeugungsdatum "
        )
        try:
            interval_start = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            published_at = _local_publication(publication_raw)
        except ValueError as exc:
            warnings.append(f"{record_id}: {exc}")
            continue
        records.append(
            HistoricalMeasure(
                record_id=record_id,
                interval_start=interval_start,
                interval_end=interval_start + timedelta(minutes=15),
                published_at=published_at,
                revision=int(revision_raw),
                increase_mw=_value(body, "Erhöhung"),
                reduction_mw=_value(body, "Reduktion"),
                displayed_date=displayed_date,
                displayed_interval=displayed_interval,
                publication_time_raw=publication_raw,
            )
        )
    return records, warnings


def profile_history_page(
    records: list[HistoricalMeasure],
    warnings: list[str],
    *,
    requested_date: date,
    snapshot_hash: str,
) -> dict[str, Any]:
    intervals = {item.interval_start for item in records}
    local_dates = {item.interval_start.astimezone(BERLIN).date() for item in records}
    revision_counts: dict[datetime, int] = {}
    for item in records:
        revision_counts[item.interval_start] = max(
            revision_counts.get(item.interval_start, 0), item.revision
        )
    return {
        "schema_version": "fifty-hertz-history-quality-v1",
        "source_id": SOURCE_ID,
        "requested_date": requested_date.isoformat(),
        "snapshot_hash": snapshot_hash,
        "record_count": len(records),
        "unique_intervals": len(intervals),
        "maximum_revision": max((item.revision for item in records), default=None),
        "revised_intervals": sum(value > 1 for value in revision_counts.values()),
        "selected_date_matches": local_dates in ({requested_date}, set()),
        "valid_empty": not records and not warnings,
        "parse_warnings": warnings,
        "publication_time_validated": not warnings and bool(records),
        "revision_history_observed": any(item.revision > 1 for item in records),
        "revision_history_complete": False,
        "zero_semantics_validated": False,
        "units_validated": all(
            item.increase_mw is not None and item.reduction_mw is not None for item in records
        ),
        "geographic_resolution": "50hertz_control_area",
        "training_admitted": False,
    }


def capture_history_date(
    requested_date: date,
    data_root: Path,
    *,
    client: httpx.Client | None = None,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    own_client = client is None
    http = client or httpx.Client(timeout=90, follow_redirects=True)
    timestamp = retrieved_at or datetime.now(timezone.utc)
    url = f"{BASE_URL}?rma-5_date={requested_date.isoformat()}"
    try:
        response = http.get(url, headers={"User-Agent": "GridPulseCapacityBacktest/0.2"})
        response.raise_for_status()
        records, warnings = parse_history_page(response.content)
        if "rma-data-timeslots" not in response.text:
            raise ValueError("50Hertz historical page marker is missing")
        stored = SnapshotStore(data_root).capture(
            source_id=SOURCE_ID,
            publisher=PUBLISHER,
            source_url=url,
            content=response.content,
            extension="html",
            retrieved_at=timestamp,
            request={"date": requested_date.isoformat()},
            response_headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() in {"content-type", "content-length", "etag", "last-modified"}
            },
            status="success_with_records" if records else "success_empty_unvalidated",
            truth_class="operator_published",
            geographic_resolution="50hertz_control_area",
            licence="unconfirmed",
            limitations=(
                "Control-area aggregate; not nodal loading or available connection capacity.",
                "An empty page is not interpreted as zero redispatch until coverage is validated.",
            ),
            adapter_version=ADAPTER_VERSION,
        )
        profile = profile_history_page(
            records, warnings, requested_date=requested_date, snapshot_hash=stored.sha256
        )
        quality = data_root / "quality" / SOURCE_ID / f"{requested_date.isoformat()}.json"
        atomic_write(quality, (json_dumps(profile) + "\n").encode())
        normalized = data_root / "normalized" / "grid-events-v1" / SOURCE_ID
        event_rows = [
            event.as_dict()
            for item in records
            for event in item.events(
                retrieved_at=timestamp, snapshot_hash=stored.sha256, source_url=url
            )
        ]
        destination = normalized / f"{requested_date.isoformat()}-{stored.sha256[:12]}.jsonl"
        atomic_write(
            destination,
            (
                ("\n".join(json_dumps(row) for row in event_rows) + "\n") if event_rows else ""
            ).encode(),
        )
        return {
            "date": requested_date.isoformat(),
            "status": "captured",
            "records": len(records),
            "events": len(event_rows),
            "blob_reused": stored.blob_reused,
            "manifest": str(stored.manifest_path),
            "quality": str(quality),
            "normalized": str(destination),
            "profile": profile,
        }
    finally:
        if own_client:
            http.close()


def json_dumps(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def capture_history_dates(
    dates: list[date], data_root: Path, *, delay_seconds: float = 0.25, workers: int = 1
) -> list[dict[str, Any]]:
    if workers < 1 or workers > 4:
        raise ValueError("workers must be between 1 and 4")
    if workers > 1:
        results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for index, requested_date in enumerate(dates):
                if index and delay_seconds:
                    time.sleep(delay_seconds)
                futures[executor.submit(capture_history_date, requested_date, data_root)] = (
                    requested_date
                )
            for future in as_completed(futures):
                requested_date = futures[future]
                try:
                    results.append(future.result())
                except (httpx.HTTPError, OSError, ValueError, UnicodeError) as exc:
                    results.append(
                        {
                            "date": requested_date.isoformat(),
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
        return sorted(results, key=lambda item: str(item["date"]))
    results = []
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for index, requested_date in enumerate(dates):
            if index:
                time.sleep(delay_seconds)
            try:
                results.append(capture_history_date(requested_date, data_root, client=client))
            except (httpx.HTTPError, OSError, ValueError, UnicodeError) as exc:
                results.append(
                    {"date": requested_date.isoformat(), "status": "failed", "error": str(exc)}
                )
    return results


def parse_history_csv(content: bytes) -> list[HistoricalMeasure]:
    """Parse the official UTC export, which exposes only the latest version per interval."""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";")
    records = []
    for row in reader:
        record_id = str(row.get("ID", "")).strip()
        match = re.fullmatch(r"Redispatch_(\d{14})_(\d{3})", record_id)
        if not match:
            raise ValueError(f"invalid 50Hertz record ID: {record_id}")
        interval_start = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
        publication_raw = str(row.get("Erzeugungsdatum (UTC)", "")).strip()
        published_at = datetime.strptime(publication_raw, "%d.%m.%Y %H:%M").replace(
            tzinfo=timezone.utc
        )
        records.append(
            HistoricalMeasure(
                record_id=record_id,
                interval_start=interval_start,
                interval_end=interval_start + timedelta(minutes=15),
                published_at=published_at,
                revision=int(match.group(2)),
                increase_mw=_csv_number(row.get("Erhöhung")),
                reduction_mw=_csv_number(row.get("Reduktion")),
                displayed_date=str(row.get("Datum", "")),
                displayed_interval=f"{row.get('von (UTC)', '')} - {row.get('bis (UTC)', '')}",
                publication_time_raw=publication_raw,
            )
        )
    return records


def _csv_number(value: object) -> float | None:
    raw = str(value or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def capture_history_csv(start: date, end: date, data_root: Path) -> dict[str, Any]:
    params = {"from": start.isoformat(), "to": end.isoformat(), "zone": "UTC"}
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        response = client.get(
            CSV_URL, params=params, headers={"User-Agent": "GridPulseCapacityBacktest/0.2"}
        )
        response.raise_for_status()
    records = parse_history_csv(response.content)
    retrieved_at = datetime.now(timezone.utc)
    stored = SnapshotStore(data_root).capture(
        source_id=f"{SOURCE_ID}_latest_csv",
        publisher=PUBLISHER,
        source_url=CSV_URL,
        content=response.content,
        extension="csv",
        retrieved_at=retrieved_at,
        request=params,
        response_headers={
            key: value
            for key, value in response.headers.items()
            if key.lower()
            in {"content-type", "content-length", "etag", "last-modified", "content-disposition"}
        },
        truth_class="operator_published",
        geographic_resolution="50hertz_control_area",
        licence="unconfirmed",
        adapter_version=ADAPTER_VERSION,
        limitations=(
            "CSV contains the latest published version per interval, not every historical revision.",
            "Control-area aggregate; not nodal loading or available connection capacity.",
        ),
    )
    unique_intervals = {item.interval_start for item in records}
    profile = {
        "schema_version": "fifty-hertz-history-csv-quality-v1",
        "source_id": f"{SOURCE_ID}_latest_csv",
        "snapshot_hash": stored.sha256,
        "coverage_start": min(unique_intervals).isoformat() if unique_intervals else None,
        "coverage_end": max(unique_intervals).isoformat() if unique_intervals else None,
        "records": len(records),
        "unique_intervals": len(unique_intervals),
        "duplicate_intervals": len(records) - len(unique_intervals),
        "maximum_revision": max((item.revision for item in records), default=None),
        "intervals_with_revision_above_one": sum(item.revision > 1 for item in records),
        "units_validated": all(
            item.increase_mw is not None and item.reduction_mw is not None for item in records
        ),
        "publication_timezone": "UTC",
        "revision_history_complete": False,
        "training_admitted": False,
    }
    quality = (
        data_root / "quality" / SOURCE_ID / f"latest-{start.isoformat()}_{end.isoformat()}.json"
    )
    atomic_write(quality, (json_dumps(profile) + "\n").encode())
    return {
        "blob": str(stored.blob_path),
        "manifest": str(stored.manifest_path),
        "quality": str(quality),
        "profile": profile,
    }
