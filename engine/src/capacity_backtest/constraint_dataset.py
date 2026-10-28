"""Build a leakage-safe hourly 50Hertz control-area constraint dataset."""

from __future__ import annotations

import bisect
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .fifty_hertz_history import (
    SOURCE_ID,
    HistoricalMeasure,
    parse_history_csv,
    parse_history_page,
)
from .storage import atomic_write, captured_blobs

BERLIN = ZoneInfo("Europe/Berlin")
LATEST_SOURCE_ID = f"{SOURCE_ID}_latest_csv"


@dataclass(frozen=True)
class ConstraintRow:
    issue_time: str
    hour: int
    weekday: int
    month: int
    redispatch_mw_lag_1h: float | None
    redispatch_mw_lag_24h: float | None
    redispatch_mw_lag_168h: float | None
    active_intervals_lag_1h: int | None
    active_intervals_lag_24h: int | None
    active_intervals_lag_168h: int | None
    source_available: bool
    revision_complete: bool
    target_constraint: bool | None
    target_resolution: str = "50hertz_control_area"
    truth_class: str = "operator_published_context"


def _latest_csv(data_root: Path) -> tuple[Path, dict[str, object]]:
    captures = captured_blobs(data_root, LATEST_SOURCE_ID)
    if not captures:
        raise RuntimeError("50Hertz latest CSV capture is unavailable")
    return captures[-1]


def _history_pages(data_root: Path) -> dict[date, tuple[Path, dict[str, object]]]:
    pages = {}
    for path, manifest in captured_blobs(data_root, SOURCE_ID):
        request = manifest.get("request", {})
        value = request.get("date") if isinstance(request, dict) else None
        if value:
            pages[date.fromisoformat(str(value))] = (path, manifest)
    return pages


def _timeline(records: list[HistoricalMeasure]) -> tuple[list[datetime], list[float]]:
    ordered = sorted(records, key=lambda item: (item.published_at, item.revision))
    return (
        [item.published_at for item in ordered],
        [float(item.increase_mw or 0) + float(item.reduction_mw or 0) for item in ordered],
    )


def _known_value(
    timeline: tuple[list[datetime], list[float]], issue_time: datetime
) -> float | None:
    timestamps, values = timeline
    index = bisect.bisect_right(timestamps, issue_time) - 1
    return values[index] if index >= 0 else None


def build_constraint_dataset(data_root: Path, *, horizon_hours: int = 24) -> dict[str, object]:
    csv_path, csv_manifest = _latest_csv(data_root)
    final_records = parse_history_csv(csv_path.read_bytes())
    pages = _history_pages(data_root)
    revision_dates = {
        item.interval_start.astimezone(BERLIN).date() for item in final_records if item.revision > 1
    }
    missing_revision_dates = sorted(revision_dates - set(pages))
    if missing_revision_dates:
        raise RuntimeError(
            f"historical revision pages are incomplete: {len(missing_revision_dates)} dates missing"
        )

    by_interval: dict[datetime, list[HistoricalMeasure]] = {}
    page_hashes = []
    for local_date in sorted(revision_dates):
        path, manifest = pages[local_date]
        records, warnings = parse_history_page(path.read_bytes())
        if warnings:
            raise RuntimeError(f"historical revision page {local_date} has parse warnings")
        page_hashes.append(str(manifest["sha256"]))
        for item in records:
            by_interval.setdefault(item.interval_start, []).append(item)
    for item in final_records:
        if item.interval_start.astimezone(BERLIN).date() not in revision_dates:
            by_interval[item.interval_start] = [item]

    final_by_interval = {item.interval_start: item for item in final_records}
    full_days: dict[date, set[datetime]] = {}
    for timestamp in final_by_interval:
        full_days.setdefault(timestamp.date(), set()).add(timestamp)
    complete_days = sorted(day for day, values in full_days.items() if len(values) == 96)
    if not complete_days:
        raise RuntimeError("50Hertz CSV contains no complete UTC days")
    start = datetime.combine(complete_days[0], datetime.min.time(), timezone.utc)
    end = datetime.combine(complete_days[-1] + timedelta(days=1), datetime.min.time(), timezone.utc)
    timelines = {timestamp: _timeline(records) for timestamp, records in by_interval.items()}

    rows = []
    issue = start + timedelta(hours=168)
    while issue + timedelta(hours=horizon_hours) <= end:
        lag_values = []
        lag_counts = []
        source_available = True
        for lag in (1, 24, 168):
            values = []
            lag_start = issue - timedelta(hours=lag)
            for quarter in range(4):
                timestamp = lag_start + timedelta(minutes=15 * quarter)
                timeline = timelines.get(timestamp)
                value = _known_value(timeline, issue) if timeline else None
                if value is None:
                    source_available = False
                else:
                    values.append(value)
            lag_values.append(sum(values) / 4 if len(values) == 4 else None)
            lag_counts.append(sum(value > 0 for value in values) if len(values) == 4 else None)

        target_points = [
            issue + timedelta(minutes=15 * quarter) for quarter in range(horizon_hours * 4)
        ]
        target_records = [final_by_interval.get(timestamp) for timestamp in target_points]
        target_complete = all(item is not None for item in target_records)
        target = (
            any(
                float(item.increase_mw or 0) > 0 or float(item.reduction_mw or 0) > 0
                for item in target_records
                if item is not None
            )
            if target_complete
            else None
        )
        rows.append(
            ConstraintRow(
                issue_time=issue.isoformat(),
                hour=issue.hour,
                weekday=issue.weekday(),
                month=issue.month,
                redispatch_mw_lag_1h=lag_values[0],
                redispatch_mw_lag_24h=lag_values[1],
                redispatch_mw_lag_168h=lag_values[2],
                active_intervals_lag_1h=lag_counts[0],
                active_intervals_lag_24h=lag_counts[1],
                active_intervals_lag_168h=lag_counts[2],
                source_available=source_available,
                revision_complete=True,
                target_constraint=target,
            )
        )
        issue += timedelta(hours=1)

    inputs = [str(csv_manifest["sha256"]), *sorted(set(page_hashes))]
    dataset_id = hashlib.sha256(
        json.dumps(
            {
                "schema": "50hertz-constraint-hourly-v1",
                "horizon": horizon_hours,
                "inputs": inputs,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    destination = data_root / "features" / "50hertz-constraint-hourly-v1" / dataset_id
    feature_path = destination / "rows.jsonl"
    atomic_write(
        feature_path,
        ("\n".join(json.dumps(asdict(row), sort_keys=True) for row in rows) + "\n").encode(),
    )
    profile = {
        "schema_version": "50hertz-constraint-dataset-quality-v1",
        "dataset_id": dataset_id,
        "rows": len(rows),
        "coverage_start": rows[0].issue_time if rows else None,
        "coverage_end": rows[-1].issue_time if rows else None,
        "horizon_hours": horizon_hours,
        "positive_targets": sum(row.target_constraint is True for row in rows),
        "unknown_targets": sum(row.target_constraint is None for row in rows),
        "missing_feature_rows": sum(not row.source_available for row in rows),
        "revision_dates": len(revision_dates),
        "revision_pages": len(pages),
        "input_hashes": inputs,
        "geographic_resolution": "50hertz_control_area",
        "capacity_claim": False,
        "training_admitted": False,
        "experimental_analysis_allowed": True,
        "admission_scope": "experimental control-area constraint-risk research only; release gate remains failed",
        "limitations": [
            "The official CSV exposes final interval outcomes; HTML pages provide observed revision chains.",
            "No output is a Berlin/Brandenburg node measurement or available-MW estimate.",
        ],
    }
    profile_path = destination / "quality.json"
    atomic_write(profile_path, (json.dumps(profile, indent=2) + "\n").encode())
    return {"features": str(feature_path), "quality": str(profile_path), "profile": profile}
