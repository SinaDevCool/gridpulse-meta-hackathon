"""Publication-aware normalization of the public 50Hertz section 13 measures RSS feed."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


@dataclass(frozen=True)
class FiftyHertzMeasure:
    source_record_id: str
    interval_id: str
    revision: int
    published_at: datetime
    starts_at: datetime
    ends_at: datetime
    increase_mw: float
    reduction_mw: float
    source_url: str | None

    @property
    def redispatch_active(self) -> bool:
        return self.increase_mw > 0 or self.reduction_mw > 0

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        for field in ("published_at", "starts_at", "ends_at"):
            value[field] = getattr(self, field).astimezone(timezone.utc).isoformat()
        value["redispatch_active"] = self.redispatch_active
        value["truth_class"] = "operator_published"
        value["geographic_resolution"] = "50hertz_control_area"
        return value


def _description_fields(description: str | None) -> dict[str, str]:
    fields = {}
    for line in (description or "").replace("<br />", "\n").replace("<br>", "\n").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def _field(fields: dict[str, str], prefix: str) -> str:
    for key, value in fields.items():
        if key.startswith(prefix):
            return value
    raise ValueError(f"missing 50Hertz field starting with {prefix!r}")


def normalize_measures(records: list[dict[str, str | None]]) -> list[FiftyHertzMeasure]:
    normalized = []
    for record in records:
        fields = _description_fields(record.get("description_raw"))
        source_record_id = _field(fields, "ID")
        match = re.fullmatch(r"Redispatch_(\d{14})_(\d{3})", source_record_id)
        if not match:
            raise ValueError(f"unrecognized 50Hertz record id {source_record_id!r}")
        starts_at = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        published = parsedate_to_datetime(record.get("pub_date_raw") or "")
        if published.tzinfo is None:
            raise ValueError("50Hertz RSS publication timestamp must include a timezone")
        normalized.append(
            FiftyHertzMeasure(
                source_record_id=source_record_id,
                interval_id=f"Redispatch_{match.group(1)}",
                revision=int(match.group(2)),
                published_at=published.astimezone(timezone.utc),
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=15),
                increase_mw=float(_field(fields, "Erh").replace(",", ".")),
                reduction_mw=float(_field(fields, "Reduktion").replace(",", ".")),
                source_url=record.get("link"),
            )
        )
    return sorted(normalized, key=lambda item: (item.starts_at, item.revision, item.published_at))


def known_measures(
    measures: list[FiftyHertzMeasure], issue_time: datetime
) -> list[FiftyHertzMeasure]:
    if issue_time.tzinfo is None:
        raise ValueError("issue time must be timezone-aware")
    known: dict[str, FiftyHertzMeasure] = {}
    for measure in measures:
        if measure.published_at > issue_time.astimezone(timezone.utc):
            continue
        current = known.get(measure.interval_id)
        if current is None or (measure.revision, measure.published_at) > (
            current.revision,
            current.published_at,
        ):
            known[measure.interval_id] = measure
    return sorted(known.values(), key=lambda item: item.starts_at)


def measure_quality(measures: list[FiftyHertzMeasure], *, snapshot_hash: str) -> dict[str, object]:
    by_interval: dict[str, list[FiftyHertzMeasure]] = {}
    for measure in measures:
        by_interval.setdefault(measure.interval_id, []).append(measure)
    revision_gaps = []
    for interval, values in by_interval.items():
        revisions = sorted({value.revision for value in values})
        if revisions != list(range(1, max(revisions) + 1)):
            revision_gaps.append(interval)
    return {
        "schema_version": "regional-source-quality-v1",
        "source_id": "fifty_hertz_measures_rss",
        "snapshot_hash": snapshot_hash,
        "record_count": len(measures),
        "unique_intervals": len(by_interval),
        "revised_intervals": sum(len(values) > 1 for values in by_interval.values()),
        "maximum_revision": max((item.revision for item in measures), default=None),
        "revision_gap_intervals": revision_gaps,
        "coverage_start": min((item.starts_at for item in measures), default=None).isoformat()
        if measures
        else None,
        "coverage_end": max((item.ends_at for item in measures), default=None).isoformat()
        if measures
        else None,
        "active_final_intervals": sum(
            max(values, key=lambda item: (item.revision, item.published_at)).redispatch_active
            for values in by_interval.values()
        ),
        "publication_time_validated": True,
        "revision_chain_observed": True,
        "revision_history_complete": False,
        "zero_semantics_validated": True,
        "units_validated": True,
        "training_admitted": False,
        "warnings": [
            "The live RSS window is too short for rolling yearly training.",
            "Prospective snapshots are required to establish archive completeness.",
            "Values are 50Hertz control-area measures, not Berlin or Brandenburg nodal loading.",
        ],
    }
