"""Schema-first data understanding gates for ENTSO-E observations."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from math import isnan

from .entsoe import EntsoeSeries


@dataclass(frozen=True)
class SeriesProfile:
    accepted: bool
    document_type: str
    series_count: int
    units: dict[str, int]
    resolutions: dict[str, int]
    business_types: dict[str, int]
    production_types: dict[str, int]
    directions: dict[str, int]
    point_count: int
    duplicate_points: int
    first_timestamp: str | None
    last_timestamp: str | None
    missing_intervals: int
    negative_values: int
    zero_values: int
    minimum: float | None
    maximum: float | None
    reasons: list[str]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def profile_entsoe(series: list[EntsoeSeries], document_type: str) -> SeriesProfile:
    reasons: list[str] = []
    if not series:
        reasons.append("document contains no parseable time series")
    units = Counter(item.unit for item in series)
    resolutions = Counter(item.resolution or "mixed_or_unknown" for item in series)
    business_types = Counter(item.business_type or "unknown" for item in series)
    production_types = Counter(item.production_type or "not_applicable" for item in series)
    directions = Counter(item.direction or "not_applicable" for item in series)
    timestamps = [timestamp for item in series for timestamp in item.points]
    values = [value for item in series for value in item.points.values()]
    identities: set[tuple[str | None, str | None, datetime]] = set()
    duplicate_points = 0
    for item in series:
        for timestamp in item.points:
            identity = (item.production_type, item.direction, timestamp)
            duplicate_points += identity in identities
            identities.add(identity)
    if units and set(units) != {"MAW"}:
        reasons.append(f"unexpected or mixed units: {dict(units)}")
    if "mixed_or_unknown" in resolutions:
        reasons.append("a series has mixed or unsupported resolution")
    if any(isnan(value) for value in values):
        reasons.append("NaN observations present")
    if document_type == "A65":
        if len(series) != 1:
            reasons.append("actual total load must contain exactly one area-total series")
        if set(business_types) != {"A04"}:
            reasons.append("actual total load has unexpected business type")
        if series and series[0].object_aggregation != "A01":
            reasons.append("actual total load is not area aggregated")
    elif document_type == "A75":
        if any(item.production_type is None for item in series):
            reasons.append("generation series lacks production-type classification")
        series_identities = {(item.production_type, item.direction) for item in series}
        if len(series_identities) != len(series):
            reasons.append("generation contains duplicate type/direction series; revision selection required")
        if any(item.direction not in {"generation", "consumption"} for item in series):
            reasons.append("generation series lacks an interpretable direction")
    ordered = sorted(set(timestamps))
    missing = 0
    if ordered and resolutions:
        minutes = {"PT15M": 15, "PT30M": 30, "PT60M": 60}
        if len(resolutions) == 1 and next(iter(resolutions)) in minutes:
            step = timedelta(minutes=minutes[next(iter(resolutions))])
            missing = sum(
                max(0, int((current - previous) / step) - 1)
                for previous, current in pairwise(ordered)
            )
            if missing:
                reasons.append(f"timeline contains {missing} missing intervals")
    return SeriesProfile(
        accepted=not reasons,
        document_type=document_type,
        series_count=len(series),
        units=dict(units),
        resolutions=dict(resolutions),
        business_types=dict(business_types),
        production_types=dict(production_types),
        directions=dict(directions),
        point_count=len(values),
        duplicate_points=duplicate_points,
        first_timestamp=min(timestamps).astimezone(timezone.utc).isoformat() if timestamps else None,
        last_timestamp=max(timestamps).astimezone(timezone.utc).isoformat() if timestamps else None,
        missing_intervals=missing,
        negative_values=sum(value < 0 for value in values),
        zero_values=sum(value == 0 for value in values),
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        reasons=reasons,
    )


def assert_profile_accepted(profile: SeriesProfile) -> None:
    if not profile.accepted:
        raise ValueError("dataset quarantined: " + "; ".join(profile.reasons))
