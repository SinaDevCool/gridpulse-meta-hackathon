"""Versioned, publication-time-aware canonical grid-event records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class GeographicResolution(str, Enum):
    BIDDING_ZONE = "bidding_zone"
    CONTROL_AREA = "control_area"
    BUNDESLAND = "bundesland"
    SERVICE_AREA = "operator_service_area"
    ASSET = "asset"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GridEvent:
    # The first fields retain the v0 positional interface.
    event_id: str
    published_at: datetime
    starts_at: datetime
    ends_at: datetime
    operator: str
    area: str
    kind: str
    direction: str | None
    power_mw: float | None
    energy_mwh: float | None
    revision: int
    truth_class: str = "operator_published"
    schema_version: str = "grid-event-v1"
    source_id: str = "unknown"
    source_record_id: str = "unknown"
    retrieved_at: datetime | None = None
    bidding_zone: str | None = None
    control_area: str | None = None
    region: str | None = None
    affected_asset_ids: tuple[str, ...] = ()
    affected_geography: str | None = None
    reason: str | None = None
    status: str | None = None
    geographic_resolution: GeographicResolution = GeographicResolution.UNKNOWN
    asset_match_confidence: float | None = None
    source_url: str = ""
    snapshot_hash: str = ""
    validation_warnings: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        required = {
            "event_id": self.event_id,
            "source_id": self.source_id,
            "source_record_id": self.source_record_id,
            "operator": self.operator,
            "area": self.area,
            "kind": self.kind,
            "source_url": self.source_url,
            "snapshot_hash": self.snapshot_hash,
        }
        if any(not value or value == "unknown" for value in required.values()):
            raise ValueError(
                "validated event identity, source, operator, area, type, URL and hash are required"
            )
        if self.retrieved_at is None:
            raise ValueError("retrieved_at is required and must not substitute for published_at")
        for name, value in (
            ("published_at", self.published_at),
            ("starts_at", self.starts_at),
            ("ends_at", self.ends_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.retrieved_at is not None and (
            self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None
        ):
            raise ValueError("retrieved_at must be timezone-aware")
        if self.ends_at.astimezone(timezone.utc) <= self.starts_at.astimezone(timezone.utc):
            raise ValueError("event end must be after start")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if self.power_mw is not None and self.power_mw < 0:
            raise ValueError("power_mw must be non-negative; direction carries sign")
        if self.energy_mwh is not None and self.energy_mwh < 0:
            raise ValueError("energy_mwh must be non-negative; direction carries sign")
        if self.asset_match_confidence is not None and not 0 <= self.asset_match_confidence <= 1:
            raise ValueError("asset_match_confidence must be between zero and one")
        if self.geographic_resolution == GeographicResolution.ASSET and not self.affected_asset_ids:
            raise ValueError("asset resolution requires at least one affected asset identifier")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        for name in ("published_at", "starts_at", "ends_at", "retrieved_at"):
            if value[name] is not None:
                value[name] = getattr(self, name).astimezone(timezone.utc).isoformat()
        value["geographic_resolution"] = self.geographic_resolution.value
        return value


def known_events(events: list[GridEvent], prediction_time: datetime) -> list[GridEvent]:
    """Return the last revision actually published by the simulated issue time."""
    if prediction_time.tzinfo is None or prediction_time.utcoffset() is None:
        raise ValueError("prediction_time must be timezone-aware")
    known: dict[tuple[str, str], GridEvent] = {}
    for event in events:
        event.validate()
        if event.published_at.astimezone(timezone.utc) > prediction_time.astimezone(timezone.utc):
            continue
        key = (event.source_id, event.event_id)
        current = known.get(key)
        if current is None or (event.revision, event.published_at.astimezone(timezone.utc)) > (
            current.revision,
            current.published_at.astimezone(timezone.utc),
        ):
            known[key] = event
    return sorted(known.values(), key=lambda item: (item.starts_at, item.source_id, item.event_id))


def event_features(events: list[GridEvent], prediction_time: datetime) -> dict[str, float | None]:
    active = [
        event
        for event in known_events(events, prediction_time)
        if event.starts_at.astimezone(timezone.utc)
        <= prediction_time.astimezone(timezone.utc)
        < event.ends_at.astimezone(timezone.utc)
        and event.status != "cancelled"
    ]
    known_power = [event.power_mw for event in active if event.power_mw is not None]
    return {
        "active_event_count": float(len(active)),
        # Null is preserved when power is unknown for every active record.
        "active_known_power_mw": sum(known_power) if known_power else None,
        "unknown_power_event_count": float(sum(event.power_mw is None for event in active)),
    }
