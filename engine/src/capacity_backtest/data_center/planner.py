"""Bounded facility planning with a conservative replayable fallback."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase2.battery import BatteryConfig
from capacity_backtest.phase2.fatigue import FatigueLimits
from capacity_backtest.phase2.thermal_workload import CoolingConfig

from .contracts import FacilityOptimizationPolicy, FlexibilityEconomics, PlanningInterval
from .acceptance import accepted_optimization
from .facility import FacilityConfig, FacilityPowerTrajectory, build_facility_trajectory
from .optimizer import FacilityOptimizationResult, optimize_facility_flexibility
from .portfolio import PortfolioTrajectory, WorkloadPortfolio, evaluate_portfolio
from .power_profiles import PiecewiseLinearPowerProfile


@dataclass(frozen=True)
class SafeFallbackPlan:
    reason: str
    portfolio: PortfolioTrajectory
    facility: FacilityPowerTrajectory
    conditional_flexibility_enabled: bool = False
    automatic_live_dispatch_authorized: bool = False
    physical_feasibility_established: bool = False


@dataclass(frozen=True)
class FacilityPlan:
    optimization: FacilityOptimizationResult
    fallback: SafeFallbackPlan | None
    accepted: bool
    used_fallback: bool
    automatic_live_dispatch_authorized: bool = False


def plan_facility_with_fallback(
    requirement: FlexibilityRequirement,
    intervals: tuple[PlanningInterval, ...],
    facility: FacilityConfig,
    portfolio: WorkloadPortfolio,
    profiles: dict[str, PiecewiseLinearPowerProfile],
    policy: FacilityOptimizationPolicy,
    economics: FlexibilityEconomics,
    *,
    cooling: CoolingConfig,
    batteries: tuple[BatteryConfig, ...] = (),
    onsite_generation_mw: tuple[float, ...] | None = None,
    fatigue_limits: FatigueLimits | None = None,
) -> FacilityPlan:
    result = optimize_facility_flexibility(
        requirement, intervals, facility, portfolio, profiles, policy, economics,
        cooling=cooling, batteries=batteries,
        onsite_generation_mw=onsite_generation_mw, fatigue_limits=fatigue_limits,
    )
    if accepted_optimization(result):
        return FacilityPlan(result, None, True, False)
    baseline_portfolio = evaluate_portfolio(
        portfolio, profiles, intervals, (), site_id=facility.site_id
    )
    baseline_facility = build_facility_trajectory(
        facility, intervals, baseline_portfolio, onsite_generation_mw=onsite_generation_mw
    )
    fallback = SafeFallbackPlan(
        f"optimization_{result.status}", baseline_portfolio, baseline_facility
    )
    return FacilityPlan(result, fallback, False, True)
