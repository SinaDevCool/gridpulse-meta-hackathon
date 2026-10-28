"""Cross-channel telemetry, clock, and energy-consistency quality gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from capacity_backtest.domain.base import parse_aware_timestamp

from .observations import ComponentObservation


@dataclass(frozen=True)
class TelemetryQualityAssessment:
    accepted: bool
    maximum_clock_offset_seconds: float
    maximum_sampling_jitter_seconds: float
    energy_residual_fraction: float
    missing_count: int
    suspect_count: int
    blockers: tuple[str, ...]


def assess_component_telemetry(
    observations: tuple[ComponentObservation, ...],
    *,
    reference_times: tuple[str, ...],
    supplied_energy_mwh: float,
    consumed_energy_mwh: float,
    maximum_clock_offset_seconds: float = 5.0,
    maximum_sampling_jitter_seconds: float = 5.0,
    maximum_energy_residual_fraction: float = 0.01,
) -> TelemetryQualityAssessment:
    if not observations or not reference_times:
        raise ValueError("telemetry quality requires observations and reference times")
    references = [parse_aware_timestamp(value, "reference time") for value in reference_times]
    offsets = []
    by_measurement: dict[str, list[datetime]] = {}
    for observation in observations:
        observation.validate()
        event = parse_aware_timestamp(observation.event_at, "event_at")
        offsets.append(min(abs((event - reference).total_seconds()) for reference in references))
        by_measurement.setdefault(observation.measurement_id, []).append(event)
    expected_step = min(
        ((b - a).total_seconds() for a, b in pairwise(references)),
        default=0.0,
    )
    jitter: list[float] = []
    for rows in by_measurement.values():
        ordered = sorted(rows)
        jitter.extend(
            abs((b - a).total_seconds() - expected_step) for a, b in pairwise(ordered)
        )
    residual = abs(supplied_energy_mwh - consumed_energy_mwh) / supplied_energy_mwh if supplied_energy_mwh else float(consumed_energy_mwh > 0)
    missing = sum(item.quality == "missing" for item in observations)
    suspect = sum(item.quality in {"suspect", "invalid"} for item in observations)
    blockers = []
    if max(offsets, default=0.0) > maximum_clock_offset_seconds:
        blockers.append("clock_offset")
    if max(jitter, default=0.0) > maximum_sampling_jitter_seconds:
        blockers.append("sampling_jitter")
    if residual > maximum_energy_residual_fraction:
        blockers.append("energy_balance")
    if missing:
        blockers.append("missing_telemetry")
    if suspect:
        blockers.append("suspect_telemetry")
    return TelemetryQualityAssessment(
        not blockers, max(offsets, default=0.0), max(jitter, default=0.0), residual,
        missing, suspect, tuple(blockers),
    )
