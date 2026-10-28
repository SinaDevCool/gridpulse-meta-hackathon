"""Deterministic multi-workload evaluation and SLA accounting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from math import isfinite

from capacity_backtest.domain.base import DomainContract

from .contracts import (
    AIWorkload,
    PlanningInterval,
    ScheduledWorkloadAction,
    WorkloadTrajectory,
    validate_intervals,
)
from .power_profiles import PiecewiseLinearPowerProfile
from .workloads import simulate_workload


@dataclass(frozen=True)
class WorkloadPortfolio(DomainContract):
    portfolio_id: str
    workloads: tuple[AIWorkload, ...]
    schema_version: str = "gridpulse-workload-portfolio-v1"
    fleet_gpu_capacity: int | None = None
    idle_gpu_power_watts: float = 0.0

    def validate(self) -> None:
        if self.schema_version != "gridpulse-workload-portfolio-v1" or not self.portfolio_id:
            raise ValueError("invalid workload portfolio")
        # An empty portfolio is valid after compute completes: battery recovery,
        # idle IT and cooling obligations still require a full-horizon solve.
        if len({item.workload_id for item in self.workloads}) != len(self.workloads):
            raise ValueError("portfolio workloads must be unique")
        for workload in self.workloads:
            workload.validate()
        if self.fleet_gpu_capacity is not None and (
            not isinstance(self.fleet_gpu_capacity, int) or self.fleet_gpu_capacity < 1
        ):
            raise ValueError("fleet GPU capacity must be a positive integer")
        if (not isfinite(self.idle_gpu_power_watts) or self.idle_gpu_power_watts < 0
                or self.idle_gpu_power_watts > 0 and self.fleet_gpu_capacity is None):
            raise ValueError("idle GPU power requires finite nonnegative watts and a reviewed fleet capacity")


@dataclass(frozen=True)
class SLAViolation:
    workload_id: str
    code: str
    penalty_eur: float


@dataclass(frozen=True)
class PortfolioPowerPoint:
    interval_index: int
    baseline_it_power_mw: float
    scheduled_it_power_mw: float
    deferred_power_mw: float
    recovery_power_mw: float


@dataclass(frozen=True)
class PortfolioTrajectory(DomainContract):
    portfolio_id: str
    workload_trajectories: tuple[WorkloadTrajectory, ...]
    power_points: tuple[PortfolioPowerPoint, ...]
    sla_violations: tuple[SLAViolation, ...]
    total_sla_penalty_eur: float
    ending_backlog_mwh: float
    schema_version: str = "gridpulse-portfolio-trajectory-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-portfolio-trajectory-v1" or not self.power_points:
            raise ValueError("invalid portfolio trajectory")
        if self.total_sla_penalty_eur < 0 or self.ending_backlog_mwh < 0:
            raise ValueError("portfolio penalty and backlog cannot be negative")
        if [item.interval_index for item in self.power_points] != list(range(len(self.power_points))):
            raise ValueError("portfolio power points must be chronological")
        for trajectory in self.workload_trajectories:
            trajectory.validate()

    def fingerprint(self) -> str:
        self.validate()
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def evaluate_portfolio(
    portfolio: WorkloadPortfolio,
    profiles: dict[str, PiecewiseLinearPowerProfile],
    intervals: tuple[PlanningInterval, ...],
    actions: tuple[ScheduledWorkloadAction, ...],
    *,
    site_id: str,
) -> PortfolioTrajectory:
    portfolio.validate()
    validate_intervals(intervals)
    known = {item.workload_id for item in portfolio.workloads}
    if set(profiles) != known or any(action.workload_id not in known for action in actions):
        raise ValueError("portfolio profiles or actions do not match workloads")
    trajectories = tuple(
        simulate_workload(
            workload,
            profiles[workload.workload_id],
            intervals,
            tuple(action for action in actions if action.workload_id == workload.workload_id),
            initial_site_id=site_id,
        )
        for workload in portfolio.workloads
    )
    baseline_trajectories = trajectories if not actions else tuple(
        simulate_workload(workload, profiles[workload.workload_id], intervals, (), initial_site_id=site_id)
        for workload in portfolio.workloads
    )
    points = []
    for interval in intervals:
        scheduled = sum(item.points[interval.index].power_mw for item in trajectories)
        baseline = sum(item.points[interval.index].power_mw for item in baseline_trajectories)
        if portfolio.fleet_gpu_capacity is not None:
            allocated = sum(item.points[interval.index].gpu_count for item in trajectories
                            if item.points[interval.index].power_mw > 1e-9)
            baseline_allocated = sum(item.points[interval.index].gpu_count for item in baseline_trajectories
                                     if item.points[interval.index].power_mw > 1e-9)
            scheduled += max(0, portfolio.fleet_gpu_capacity - allocated) * portfolio.idle_gpu_power_watts / 1_000_000
            baseline += max(0, portfolio.fleet_gpu_capacity - baseline_allocated) * portfolio.idle_gpu_power_watts / 1_000_000
        points.append(
            PortfolioPowerPoint(
                interval.index,
                baseline,
                scheduled,
                max(0.0, baseline - scheduled),
                max(0.0, scheduled - baseline),
            )
        )
    violations = []
    if portfolio.fleet_gpu_capacity is not None:
        for interval in intervals:
            allocated = sum(
                trajectory.points[interval.index].gpu_count
                for trajectory in trajectories
                if trajectory.points[interval.index].power_mw > 1e-9
            )
            if allocated > portfolio.fleet_gpu_capacity:
                violations.append(SLAViolation("portfolio", "fleet_gpu_capacity", 0.0))
    for workload, trajectory in zip(portfolio.workloads, trajectories):
        if not trajectory.deadline_met:
            violations.append(SLAViolation(workload.workload_id, "deadline_or_completion", workload.sla.penalty_eur))
    backlog = sum(item.ending_remaining_work_hours * workload.nominal_power_mw for workload, item in zip(portfolio.workloads, trajectories))
    result = PortfolioTrajectory(
        portfolio.portfolio_id,
        trajectories,
        tuple(points),
        tuple(violations),
        sum(item.penalty_eur for item in violations),
        # Job throughput determines unfinished work. Different power caps and
        # idle fleet hours can change energy without creating unfinished jobs.
        backlog,
    )
    result.validate()
    return result
