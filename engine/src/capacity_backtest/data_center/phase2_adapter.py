"""Adapter from job-level schedules to the existing aggregate Phase 2 owner."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.phase2.thermal_workload import (
    CoolingConfig,
    ThermalWorkloadTrajectory,
    WorkloadConfig,
    simulate_cooling_workload,
)

from .contracts import PlanningInterval, validate_intervals
from .portfolio import PortfolioTrajectory


@dataclass(frozen=True)
class AggregateWorkloadMapping:
    trajectory: ThermalWorkloadTrajectory
    job_deferred_energy_mwh: float
    job_recovery_energy_mwh: float
    aggregate_ending_backlog_mwh: float
    reconciliation_error_mwh: float


def map_portfolio_to_phase2(
    portfolio: PortfolioTrajectory,
    intervals: tuple[PlanningInterval, ...],
    cooling: CoolingConfig,
    *,
    deadline_hours: int,
    tolerance_mwh: float = 1e-9,
) -> AggregateWorkloadMapping:
    portfolio.validate()
    validate_intervals(intervals)
    if len(portfolio.power_points) != len(intervals):
        raise ValueError("portfolio and aggregate horizons must align")
    interval_hours = intervals[0].duration_minutes / 60
    deferred = [point.deferred_power_mw for point in portfolio.power_points]
    recovery = [point.recovery_power_mw for point in portfolio.power_points]
    config = WorkloadConfig(
        maximum_shift_mw=max(deferred, default=0.0),
        recovery_power_mw=max(recovery, default=0.0),
        deadline_hours=deadline_hours,
        critical_fraction=0.0,
    )
    trajectory = simulate_cooling_workload(
        deferred,
        recovery,
        cooling,
        config,
        interval_hours=interval_hours,
    )
    deferred_energy = sum(deferred) * interval_hours
    recovery_energy = sum(recovery) * interval_hours
    expected_backlog = max(0.0, deferred_energy - recovery_energy)
    error = abs(trajectory.ending_workload_backlog_mwh - expected_backlog)
    if error > tolerance_mwh:
        raise ValueError("job-level and aggregate workload backlog do not reconcile")
    return AggregateWorkloadMapping(
        trajectory,
        deferred_energy,
        recovery_energy,
        trajectory.ending_workload_backlog_mwh,
        error,
    )
