"""Deterministic assessment of a supplied facility schedule against a requirement."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase2.battery import BatteryTrajectory

from .contracts import PlanningInterval, validate_intervals
from .facility import FacilityPowerTrajectory
from .phase2_adapter import AggregateWorkloadMapping
from .portfolio import PortfolioTrajectory, SLAViolation


@dataclass(frozen=True)
class FacilityFlexibilityAssessment:
    requirement_id: str
    facility_id: str
    feasible: bool
    required_reduction_mw: float
    delivered_reduction_mw: float
    shortfall_mw: float
    response_time_met: bool | None
    event_duration_met: bool | None
    recovery_complete: bool
    rebound_peak_mw: float
    rebound_limit_met: bool | None
    sla_violations: tuple[SLAViolation, ...]
    total_sla_penalty_eur: float
    import_limit_violations: int
    reactive_power_passed: bool
    battery_terminal_targets_met: bool
    truth_class: TruthClass
    blockers: tuple[str, ...]
    automatic_live_dispatch_authorized: bool = False
    schema_version: str = "gridpulse-facility-flexibility-assessment-v1"


def assess_facility_flexibility(
    requirement: FlexibilityRequirement,
    intervals: tuple[PlanningInterval, ...],
    baseline: FacilityPowerTrajectory,
    scheduled: FacilityPowerTrajectory,
    portfolio: PortfolioTrajectory,
    aggregate: AggregateWorkloadMapping | None,
    *,
    event_intervals: tuple[bool, ...],
    batteries: tuple[BatteryTrajectory, ...] = (),
    cooling_recovery_complete: bool | None = None,
    replayed_rebound_mw: float | None = None,
) -> FacilityFlexibilityAssessment:
    requirement.validate()
    validate_intervals(intervals)
    size = len(intervals)
    if not event_intervals or len(event_intervals) != size or len(baseline.points) != size or len(scheduled.points) != size:
        raise ValueError("assessment horizons must align and contain an event")
    reductions = tuple(
        max(0.0, base.grid_import_mw - actual.grid_import_mw)
        for base, actual in zip(baseline.points, scheduled.points)
    )
    delivered = min(
        (value for value, active in zip(reductions, event_intervals) if active),
        default=0.0,
    )
    shortfall = max(0.0, requirement.required_reduction_mw - delivered)
    blockers = list(requirement.blockers)
    interval_seconds = intervals[0].duration_minutes * 60
    if requirement.response_time_seconds is None or not any(event_intervals):
        response_met = None
    else:
        first_event = event_intervals.index(True)
        first_delivery = next(
            (
                index
                for index in range(first_event, size)
                if reductions[index] + 1e-9 >= requirement.required_reduction_mw
            ),
            None,
        )
        response_met = first_delivery is not None and (
            first_delivery - first_event
        ) * interval_seconds <= requirement.response_time_seconds
        if not response_met:
            blockers.append("response_time_not_met")
    event_minutes = sum(event_intervals) * intervals[0].duration_minutes
    if requirement.maximum_event_duration_minutes is None:
        duration_met = None
    else:
        duration_met = event_minutes <= requirement.maximum_event_duration_minutes
        if not duration_met:
            blockers.append("maximum_event_duration_exceeded")
    if cooling_recovery_complete is None:
        if aggregate is None:
            raise ValueError("assessment requires actual cooling replay or a legacy aggregate mapping")
        recovery_complete = (
            aggregate.trajectory.ending_thermal_debt_mwh <= 1e-9
            and aggregate.aggregate_ending_backlog_mwh <= 1e-9
            and aggregate.trajectory.deadline_violation_hours == 0
        )
    else:
        recovery_complete = (cooling_recovery_complete and portfolio.ending_backlog_mwh <= 1e-9
                             and not portfolio.sla_violations)
    if not recovery_complete:
        blockers.append("incomplete_recovery")
    if replayed_rebound_mw is not None:
        rebound = replayed_rebound_mw
    else:
        if aggregate is None:
            raise ValueError("assessment requires an actual rebound or legacy aggregate mapping")
        rebound = max(
            aggregate.trajectory.cooling_rebound_peak_mw + aggregate.trajectory.workload_rebound_peak_mw,
            max((point.recovery_power_mw for point in portfolio.power_points), default=0.0),
        )
    if requirement.rebound_limit_mw is None:
        rebound_met = None
    else:
        rebound_met = rebound <= requirement.rebound_limit_mw + 1e-9
        if not rebound_met:
            blockers.append("rebound_limit_exceeded")
    if shortfall > 1e-9:
        blockers.append("flexibility_shortfall")
    if portfolio.sla_violations:
        blockers.append("sla_violation")
    if scheduled.import_limit_violation_count:
        blockers.append("facility_import_limit")
    reactive = all(item.passed for item in scheduled.phase_power_assessments)
    if not reactive:
        blockers.append("phase_or_reactive_limits")
    battery_targets = all(item.terminal_target_met for item in batteries)
    if not battery_targets:
        blockers.append("battery_terminal_soc")
    blockers = list(dict.fromkeys(blockers))
    return FacilityFlexibilityAssessment(
        requirement.requirement_id,
        scheduled.facility_id,
        not blockers,
        requirement.required_reduction_mw,
        delivered,
        shortfall,
        response_met,
        duration_met,
        recovery_complete,
        rebound,
        rebound_met,
        portfolio.sla_violations,
        portfolio.total_sla_penalty_eur,
        scheduled.import_limit_violation_count,
        reactive,
        battery_targets,
        coerce_truth_class(requirement.truth_class),
        tuple(blockers),
    )
