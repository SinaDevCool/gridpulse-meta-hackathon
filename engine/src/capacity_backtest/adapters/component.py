"""Strict read-only adapter for DCIM, BMS, UPS, and battery-EMS observations."""

from __future__ import annotations

import json

from capacity_backtest.data_center.contracts import PlanningInterval
from capacity_backtest.data_center.measurement_boundaries import MeasuredComponent, MeteringPoint
from capacity_backtest.data_center.observations import ComponentObservation, aggregate_observations


def parse_component_observations(
    content: bytes, *, source_id: str
) -> tuple[ComponentObservation, ...]:
    if len(content) > 16 * 1024 * 1024:
        raise ValueError("component payload exceeds bounded capture size")
    payload = json.loads(content)
    if not isinstance(payload, list) or not payload:
        raise ValueError("component payload must be a non-empty JSON array")
    required = {
        "observation_id", "measurement_id", "component", "event_at", "available_at",
        "ingested_at", "sequence", "value", "unit", "quality", "evidence_sha256",
    }
    results = []
    for row in payload:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("component observation schema drift")
        normalized = dict(row)
        normalized["component"] = MeasuredComponent(str(row["component"]))
        observation = ComponentObservation(**normalized, source_id=source_id)
        observation.validate()
        results.append(observation)
    return tuple(sorted(results, key=lambda item: (item.event_at, item.sequence)))


def aggregate_component_capture(content: bytes, *, source_id: str, meter: MeteringPoint,
                                intervals: tuple[PlanningInterval, ...], planning_cutoff: str):
    """Use the sole component adapter and interval integrator for offline qualification."""
    return aggregate_observations(parse_component_observations(content, source_id=source_id),
                                  meter, intervals, planning_cutoff=planning_cutoff)
