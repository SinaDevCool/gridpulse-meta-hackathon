"""Precommitted baselines and complete delivery/recovery outcome classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from capacity_backtest.domain.base import parse_aware_timestamp


class BaselineMethod(str, Enum):
    FROZEN_PLANNER = "frozen_planner"
    RECENT_HISTORY = "recent_history"
    MATCHED_DAY = "matched_day"


@dataclass(frozen=True)
class DeliveryBaseline:
    method: BaselineMethod
    selected_at: str
    event_at: str
    values_mw: tuple[float, ...]
    error_bound_mw: float
    evidence_fingerprint: str

    def validate(self) -> None:
        selected = parse_aware_timestamp(self.selected_at, "baseline selected_at")
        event = parse_aware_timestamp(self.event_at, "baseline event_at")
        if selected >= event or not self.values_mw or min((*self.values_mw, self.error_bound_mw)) < 0:
            raise ValueError("delivery baseline must be frozen before the event")
        if len(self.evidence_fingerprint) != 64:
            raise ValueError("baseline evidence fingerprint must be SHA-256")


@dataclass(frozen=True)
class CompleteDeliveryOutcome:
    classification: str
    delivered_reduction_mw: float
    shortfall_mw: float
    response_met: bool
    duration_met: bool
    rebound_met: bool
    battery_recovered: bool
    thermal_recovered: bool
    workload_recovered: bool
    sla_met: bool
    verified: bool
    blockers: tuple[str, ...]


def verify_complete_delivery(
    baseline: DeliveryBaseline,
    observed_import_mw: tuple[float, ...],
    *,
    event_intervals: tuple[bool, ...],
    requested_reduction_mw: float,
    response_met: bool,
    rebound_mw: float,
    rebound_limit_mw: float,
    battery_recovered: bool,
    thermal_recovered: bool,
    workload_recovered: bool,
    sla_met: bool,
    telemetry_valid: bool,
) -> CompleteDeliveryOutcome:
    baseline.validate()
    if len(observed_import_mw) != len(baseline.values_mw) or len(event_intervals) != len(observed_import_mw):
        raise ValueError("delivery verification trajectories must align")
    reductions = tuple(max(0.0, base - actual) for base, actual in zip(baseline.values_mw, observed_import_mw))
    delivered = min((value for value, active in zip(reductions, event_intervals) if active), default=0.0)
    shortfall = max(0.0, requested_reduction_mw - delivered)
    duration_met = all(value + baseline.error_bound_mw >= requested_reduction_mw for value, active in zip(reductions, event_intervals) if active)
    rebound_met = rebound_mw <= rebound_limit_mw + 1e-9
    blockers: list[str] = []
    checks = {
        "telemetry_invalid": telemetry_valid,
        "response_failed": response_met,
        "partial_delivery": shortfall <= baseline.error_bound_mw,
        "duration_failed": duration_met,
        "rebound_failed": rebound_met,
        "battery_recovery_failed": battery_recovered,
        "thermal_recovery_failed": thermal_recovered,
        "workload_recovery_failed": workload_recovered,
        "sla_failed": sla_met,
    }
    blockers.extend(name for name, passed in checks.items() if not passed)
    if not telemetry_valid:
        classification = "telemetry_invalid"
    elif shortfall > baseline.error_bound_mw:
        classification = "failed_delivery"
    elif blockers:
        classification = "recovery_failed"
    else:
        classification = "passed"
    return CompleteDeliveryOutcome(
        classification, delivered, shortfall, response_met, duration_met, rebound_met,
        battery_recovered, thermal_recovered, workload_recovered, sla_met,
        not blockers, tuple(blockers),
    )
