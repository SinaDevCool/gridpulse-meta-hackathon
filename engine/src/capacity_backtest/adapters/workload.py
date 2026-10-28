"""Read-only generic workload-execution JSON adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite

from capacity_backtest.domain.base import parse_aware_timestamp


@dataclass(frozen=True)
class WorkloadExecutionObservation:
    execution_id: str
    workload_id: str
    submitted_at: str
    started_at: str
    ended_at: str
    gpu_model: str
    gpu_count: int
    power_cap_mw: float
    measured_power_mw: float
    completed_work_fraction: float
    checkpoint_count: int
    source_id: str
    reference_work_duration_minutes: float | None = None
    configuration_id: str = "legacy-unspecified"
    power_boundary: str = "gpu"
    available_at: str | None = None

    def validate(self) -> None:
        submitted = parse_aware_timestamp(self.submitted_at, "submitted_at")
        started = parse_aware_timestamp(self.started_at, "started_at")
        ended = parse_aware_timestamp(self.ended_at, "ended_at")
        if self.available_at is not None and parse_aware_timestamp(self.available_at, "available_at") < ended:
            raise ValueError("execution cannot be available before its completion")
        if not submitted <= started < ended:
            raise ValueError("workload execution times are invalid")
        if not all((self.execution_id, self.workload_id, self.gpu_model, self.source_id)):
            raise ValueError("workload execution identity is invalid")
        if not all(isfinite(v) for v in (self.power_cap_mw, self.measured_power_mw, self.completed_work_fraction)):
            raise ValueError("workload execution values must be finite")
        if not isinstance(self.gpu_count, int) or isinstance(self.gpu_count, bool) or self.gpu_count <= 0:
            raise ValueError("GPU count must be a positive integer")
        if not isinstance(self.checkpoint_count, int) or isinstance(self.checkpoint_count, bool):
            raise TypeError("checkpoint count must be an integer")
        if min(self.power_cap_mw, self.measured_power_mw, self.checkpoint_count) < 0:
            raise ValueError("workload execution values cannot be negative")
        if not self.configuration_id or self.power_boundary not in {"gpu", "it", "facility"}:
            raise ValueError("workload execution configuration or boundary is invalid")
        if self.reference_work_duration_minutes is not None and (
            not isfinite(self.reference_work_duration_minutes) or self.reference_work_duration_minutes <= 0
        ):
            raise ValueError("reference work duration must be finite positive minutes")
        if not 0 < self.completed_work_fraction <= 1:
            raise ValueError("completed work fraction must be in (0, 1]")

    def throughput_fraction(self) -> float:
        """Reference work-hours completed per elapsed hour; legacy values are preserved."""
        self.validate()
        if self.reference_work_duration_minutes is None:
            return self.completed_work_fraction
        elapsed = (parse_aware_timestamp(self.ended_at, "ended_at") - parse_aware_timestamp(self.started_at, "started_at")).total_seconds() / 60
        return self.completed_work_fraction * self.reference_work_duration_minutes / elapsed


def parse_workload_executions(
    content: bytes, *, source_id: str
) -> tuple[WorkloadExecutionObservation, ...]:
    payload = json.loads(content)
    if not isinstance(payload, list) or not payload:
        raise ValueError("workload payload must be a non-empty JSON array")
    required = {
        "execution_id", "workload_id", "submitted_at", "started_at", "ended_at",
        "gpu_model", "gpu_count", "power_cap_mw", "measured_power_mw",
        "completed_work_fraction", "checkpoint_count",
    }
    results = []
    for row in payload:
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {
            "reference_work_duration_minutes", "configuration_id", "power_boundary", "available_at"
        }:
            raise ValueError("workload execution schema drift")
        result = WorkloadExecutionObservation(**row, source_id=source_id)
        result.validate()
        results.append(result)
    return tuple(sorted(results, key=lambda item: (item.started_at, item.execution_id)))
