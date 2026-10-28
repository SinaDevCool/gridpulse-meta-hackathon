"""Canonical bitemporal component observations and alignment quality."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite

from capacity_backtest.domain.base import parse_aware_timestamp

from .contracts import PlanningInterval, validate_intervals
from .measurement_boundaries import MeasuredComponent, MeteringPoint, validate_component_unit


@dataclass(frozen=True)
class ComponentObservation:
    observation_id: str
    measurement_id: str
    component: MeasuredComponent
    event_at: str
    available_at: str
    ingested_at: str
    sequence: int
    value: float | None
    unit: str
    quality: str
    source_id: str
    evidence_sha256: str

    def validate(self) -> None:
        event = parse_aware_timestamp(self.event_at, "observation event_at")
        available = parse_aware_timestamp(self.available_at, "observation available_at")
        ingested = parse_aware_timestamp(self.ingested_at, "observation ingested_at")
        if not all((self.observation_id, self.measurement_id, self.unit, self.source_id)):
            raise ValueError("observation identity is invalid")
        if not event <= available <= ingested or self.sequence < 0:
            raise ValueError("observation bitemporal order is invalid")
        if self.quality not in {"valid", "estimated", "suspect", "invalid", "missing"}:
            raise ValueError("unsupported observation quality")
        if self.value is None and self.quality != "missing":
            raise ValueError("unknown observations must be explicitly missing")
        validate_component_unit(self.component, self.unit)
        if self.value is not None and not isfinite(self.value):
            raise ValueError("observation values must be finite")
        if self.value is not None and self.quality == "missing":
            raise ValueError("missing observations cannot contain a value")
        if not re.fullmatch(r"[a-f0-9]{64}", self.evidence_sha256):
            raise ValueError("observation evidence hash must be SHA-256")


@dataclass(frozen=True)
class AlignmentQuality:
    interval_count: int
    expected_observations: int
    valid_observations: int
    completeness_fraction: float
    duplicate_count: int
    revision_count: int
    future_leakage_count: int
    accepted: bool
    blockers: tuple[str, ...]


def align_observations(
    observations: tuple[ComponentObservation, ...],
    *,
    planning_cutoff: str,
    expected_measurement_ids: tuple[str, ...],
    interval_timestamps: tuple[str, ...],
    minimum_completeness_fraction: float = 0.95,
) -> tuple[dict[tuple[str, str], ComponentObservation], AlignmentQuality]:
    cutoff = parse_aware_timestamp(planning_cutoff, "planning cutoff")
    if not expected_measurement_ids or not interval_timestamps:
        raise ValueError("alignment requires measurements and intervals")
    if not isfinite(minimum_completeness_fraction) or not 0 <= minimum_completeness_fraction <= 1:
        raise ValueError("completeness threshold must be between zero and one")
    instants = {
        parse_aware_timestamp(value, "interval timestamp"): value for value in interval_timestamps
    }
    if len(set(expected_measurement_ids)) != len(expected_measurement_ids) or len(instants) != len(
        interval_timestamps
    ):
        raise ValueError("alignment identities and interval instants must be unique")
    for observation in observations:
        observation.validate()
    expected = len(expected_measurement_ids) * len(interval_timestamps)
    latest: dict[tuple[str, str], ComponentObservation] = {}
    duplicates = revisions = leakage = 0
    for observation in sorted(
        observations,
        key=lambda item: (parse_aware_timestamp(item.available_at, "available_at"), item.sequence),
    ):
        observation.validate()
        if observation.measurement_id not in expected_measurement_ids:
            continue
        instant = parse_aware_timestamp(observation.event_at, "event_at")
        if instant not in instants:
            continue
        if parse_aware_timestamp(observation.available_at, "available_at") > cutoff:
            leakage += 1
            continue
        key = (observation.measurement_id, instants[instant])
        if key in latest:
            duplicates += 1
            revisions += int(observation.sequence > latest[key].sequence)
        if key not in latest or observation.sequence > latest[key].sequence:
            latest[key] = observation
    valid = sum(item.quality == "valid" and item.value is not None for item in latest.values())
    completeness = valid / expected
    blockers = []
    if completeness + 1e-12 < minimum_completeness_fraction:
        blockers.append("insufficient_completeness")
    if leakage:
        blockers.append("post_cutoff_observations_excluded")
    return latest, AlignmentQuality(
        len(interval_timestamps),
        expected,
        valid,
        completeness,
        duplicates,
        revisions,
        leakage,
        not blockers,
        tuple(blockers),
    )


@dataclass(frozen=True)
class AggregatedObservation:
    interval_index: int
    mean_power_mw: float | None
    energy_mwh: float | None
    coverage_fraction: float
    source_observation_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    transformation_version: str = "interval-energy-v1"


def aggregate_observations(
    observations: tuple[ComponentObservation, ...], meter: MeteringPoint,
    intervals: tuple[PlanningInterval, ...], *, planning_cutoff: str,
    maximum_gap_seconds: int | None = None,
) -> tuple[AggregatedObservation, ...]:
    """Integrate qualified samples; never fill a gap with zero or extrapolate counters.

    Instantaneous samples use explicit bounded zero-order hold. Average samples
    describe [event_at, event_at + meter interval). Counter differences span two
    readings and assume uniform consumption within that span. Partial intervals
    return no power/energy, with coverage and provenance retained.
    """
    meter.validate()
    validate_intervals(intervals)
    cutoff = parse_aware_timestamp(planning_cutoff, "planning cutoff")
    gap = maximum_gap_seconds if maximum_gap_seconds is not None else meter.interval_seconds
    if not isinstance(gap, int) or gap <= 0:
        raise ValueError("maximum measurement gap must be positive seconds")
    if meter.unit not in {"W", "kW", "MW", "Wh", "kWh", "MWh"}:
        raise ValueError("energy aggregation requires electrical power or energy")
    latest = {}
    for row in observations:
        row.validate()
        if row.measurement_id != meter.measurement_id:
            continue
        if row.component != meter.component or row.unit != meter.unit:
            raise ValueError("observation and meter boundaries differ")
        if parse_aware_timestamp(row.available_at, "available_at") > cutoff:
            continue
        at = parse_aware_timestamp(row.event_at, "event_at")
        if meter.sample_kind == "interval_average" and parse_aware_timestamp(row.available_at, "available_at") < at + timedelta(seconds=meter.interval_seconds):
            raise ValueError("interval-average evidence cannot be available before its interval ends")
        prior = latest.get(at)
        if prior and prior.sequence == row.sequence and prior != row:
            raise ValueError("conflicting observation revisions")
        if prior is None or row.sequence > prior.sequence:
            latest[at] = row
    rows = sorted(latest.items())
    scale = {"W": 1e-6, "kW": 1e-3, "MW": 1, "Wh": 1e-6, "kWh": 1e-3, "MWh": 1}[meter.unit]
    segments = []
    for i, (start, row) in enumerate(rows):
        ids = (row.observation_id,)
        valid = row.quality == "valid" and row.value is not None
        reason = "unqualified_sample"
        if meter.sample_kind == "cumulative_energy":
            if i + 1 == len(rows):
                continue
            end, following = rows[i + 1]
            seconds = (end - start).total_seconds()
            ids += (following.observation_id,)
            valid = valid and following.quality == "valid" and following.value is not None
            delta = (following.value - row.value) if valid else 0
            if delta < 0:
                valid, reason = False, "counter_reset"
            if seconds > gap:
                valid, reason = False, "measurement_gap"
            power = delta * scale * 3600 / seconds
        else:
            end = start + timedelta(seconds=meter.interval_seconds)
            if i + 1 < len(rows):
                if meter.sample_kind == "interval_average" and rows[i + 1][0] < end:
                    raise ValueError("interval-average observations overlap")
                end = min(end, rows[i + 1][0])
            end = min(end, start + timedelta(seconds=gap))
            power = (row.value or 0) * scale
        segments.append((start, min(end, cutoff), power * meter.sign_multiplier, valid, reason, ids))
    result = []
    for interval in intervals:
        start = parse_aware_timestamp(interval.start, "interval start")
        end = start + timedelta(minutes=interval.duration_minutes)
        covered, energy, ids, blockers = 0.0, 0.0, set(), set()
        for a, b, power, valid, reason, source in segments:
            seconds = max(0.0, (min(end, b) - max(start, a)).total_seconds())
            if not seconds:
                continue
            ids.update(source)
            if valid:
                covered += seconds
                energy += power * seconds / 3600
            else:
                blockers.add(reason)
        duration = interval.duration_minutes * 60
        complete = abs(covered - duration) < 1e-6
        if not complete:
            blockers.add("incomplete_interval")
        result.append(AggregatedObservation(interval.index,
            energy * 3600 / duration if complete else None,
            energy if complete else None, min(1.0, covered / duration),
            tuple(sorted(ids)), tuple(sorted(blockers))))
    return tuple(result)
