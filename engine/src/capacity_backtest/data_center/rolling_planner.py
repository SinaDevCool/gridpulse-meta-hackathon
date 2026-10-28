"""Cutoff-safe rolling orchestration around uncertainty and the canonical optimizer."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.domain.base import parse_aware_timestamp
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase1.risk import RiskPolicy
from capacity_backtest.phase2.battery import BatteryConfig
from capacity_backtest.phase2.fatigue import FatigueLimits
from capacity_backtest.phase2.thermal_workload import CoolingConfig

from .contracts import FacilityOptimizationPolicy, FlexibilityEconomics, PlanningInterval
from .facility import FacilityConfig
from .portfolio import WorkloadPortfolio
from .power_profiles import PiecewiseLinearPowerProfile
from .uncertainty import (
    UncertainFlexibilityAssessment,
    UncertaintyScenario,
    evaluate_uncertain_flexibility,
)


@dataclass(frozen=True)
class RollingPlanningWindow:
    window_id: str
    cutoff: str
    forecast_fingerprint: str
    scenarios: tuple[UncertaintyScenario, ...]
    recalculation_reason: str

    def validate(self) -> None:
        parse_aware_timestamp(self.cutoff, "rolling cutoff")
        if not self.window_id or len(self.forecast_fingerprint) != 64 or not self.recalculation_reason:
            raise ValueError("rolling planning window is invalid")


@dataclass(frozen=True)
class RollingWindowResult:
    window_id: str
    cutoff: str
    assessment: UncertainFlexibilityAssessment
    accepted_fingerprint: str | None
    used_fallback: bool
    revision_changed: bool


@dataclass(frozen=True)
class RollingPlanningResult:
    windows: tuple[RollingWindowResult, ...]
    accepted_revisions: int
    fallback_count: int
    final_accepted_fingerprint: str | None
    automatic_live_dispatch_authorized: bool = False
    evaluation_method: str = "independent_window_benchmark_not_stateful_control"
    common_plan_validated: bool = False


def run_rolling_planner(
    windows: tuple[RollingPlanningWindow, ...],
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
    confidence: float = 0.9,
    onsite_generation_mw: tuple[float, ...] | None = None,
    fatigue_limits: FatigueLimits | None = None,
) -> RollingPlanningResult:
    if not windows or len({item.window_id for item in windows}) != len(windows):
        raise ValueError("rolling windows must be non-empty and unique")
    for window in windows:
        window.validate()
    cutoffs = [parse_aware_timestamp(item.cutoff, "rolling cutoff") for item in windows]
    if cutoffs != sorted(cutoffs) or len(set(cutoffs)) != len(cutoffs):
        raise ValueError("rolling cutoffs must be unique and chronological")
    accepted: str | None = None
    results = []
    revisions = fallbacks = 0
    for window in windows:
        assessment = evaluate_uncertain_flexibility(
            requirement, intervals, facility, portfolio, profiles, policy, economics,
            window.scenarios, cooling=cooling, batteries=batteries,
            risk_policy=RiskPolicy.CHANCE_CONSTRAINED, confidence=confidence,
            onsite_generation_mw=onsite_generation_mw, fatigue_limits=fatigue_limits,
        )
        prior = accepted
        fallback = not assessment.accepted
        if assessment.accepted:
            accepted = assessment.fingerprint
            revisions += int(accepted != prior)
        else:
            fallbacks += 1
        results.append(RollingWindowResult(
            window.window_id, window.cutoff, assessment, accepted, fallback,
            accepted is not None and accepted != prior,
        ))
    return RollingPlanningResult(tuple(results), revisions, fallbacks, accepted)
