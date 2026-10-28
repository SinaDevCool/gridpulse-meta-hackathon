"""Scenario-based uncertainty wrapper around the canonical facility optimizer."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, replace
from math import isfinite

from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase1.risk import RiskPolicy
from capacity_backtest.phase2.battery import BatteryConfig
from capacity_backtest.phase2.fatigue import FatigueLimits
from capacity_backtest.phase2.thermal_workload import CoolingConfig

from .acceptance import accepted_optimization
from .contracts import FacilityOptimizationPolicy, FlexibilityEconomics, PlanningInterval
from .facility import FacilityConfig
from .optimizer import FacilityOptimizationResult, optimize_facility_flexibility
from .portfolio import WorkloadPortfolio
from .power_profiles import PiecewiseLinearPowerProfile


@dataclass(frozen=True)
class UncertaintyScenario:
    scenario_id: str
    probability: float
    battery_temperature_c: tuple[float, ...]
    onsite_generation_mw: tuple[float, ...]
    assumption_ids: tuple[str, ...] = ()

    def validate(self, size: int) -> None:
        if not self.scenario_id or not isfinite(self.probability) or not 0 < self.probability <= 1:
            raise ValueError("scenario identity and probability are invalid")
        if len(self.battery_temperature_c) != size or len(self.onsite_generation_mw) != size:
            raise ValueError("scenario trajectories must align with the horizon")
        if not all(isfinite(v) for v in (*self.battery_temperature_c, *self.onsite_generation_mw)):
            raise ValueError("scenario trajectories must be finite")
        if min(self.onsite_generation_mw) < 0:
            raise ValueError("onsite generation cannot be negative")


@dataclass(frozen=True)
class ScenarioBounds:
    temperature_min_c: float
    temperature_max_c: float
    onsite_generation_min_mw: float
    onsite_generation_max_mw: float

    def validate(self) -> None:
        if not all(isfinite(v) for v in (self.temperature_min_c, self.temperature_max_c, self.onsite_generation_min_mw, self.onsite_generation_max_mw)):
            raise ValueError("scenario bounds must be finite")
        if self.temperature_min_c > self.temperature_max_c:
            raise ValueError("temperature scenario bounds are reversed")
        if not 0 <= self.onsite_generation_min_mw <= self.onsite_generation_max_mw:
            raise ValueError("onsite-generation scenario bounds are invalid")


def generate_uncertainty_scenarios(
    bounds: ScenarioBounds, *, horizon_size: int, count: int, seed: int
) -> tuple[UncertaintyScenario, ...]:
    """Generate a stable bounded fixture/scenario set without global random state."""

    bounds.validate()
    if horizon_size < 1 or count < 1:
        raise ValueError("scenario horizon and count must be positive")
    generator = random.Random(seed)
    probability = 1 / count
    return tuple(
        UncertaintyScenario(
            f"scenario-{index:04d}", probability,
            tuple(generator.uniform(bounds.temperature_min_c, bounds.temperature_max_c) for _ in range(horizon_size)),
            tuple(generator.uniform(bounds.onsite_generation_min_mw, bounds.onsite_generation_max_mw) for _ in range(horizon_size)),
            (f"seed:{seed}",),
        )
        for index in range(count)
    )


@dataclass(frozen=True)
class ScenarioOutcome:
    scenario_id: str
    probability: float
    status: str
    delivered_reduction_mw: float
    shortfall_mw: float
    objective_eur: float | None
    model_fingerprint: str
    physically_accepted: bool = False


@dataclass(frozen=True)
class UncertainFlexibilityAssessment:
    policy: RiskPolicy
    confidence: float
    outcomes: tuple[ScenarioOutcome, ...]
    feasibility_probability: float
    expected_shortfall_mw: float
    worst_case_shortfall_mw: float
    dependable_reduction_mw: float
    accepted: bool
    blockers: tuple[str, ...]
    fingerprint: str
    capacity_claim: bool = False
    automatic_live_dispatch_authorized: bool = False
    schema_version: str = "gridpulse-uncertain-flexibility-assessment-v1"
    evaluation_method: str = "independent_scenario_benchmark"
    common_plan_validated: bool = False


def evaluate_uncertain_flexibility(
    requirement: FlexibilityRequirement,
    intervals: tuple[PlanningInterval, ...],
    facility: FacilityConfig,
    portfolio: WorkloadPortfolio,
    profiles: dict[str, PiecewiseLinearPowerProfile],
    policy: FacilityOptimizationPolicy,
    economics: FlexibilityEconomics,
    scenarios: tuple[UncertaintyScenario, ...],
    *,
    cooling: CoolingConfig,
    batteries: tuple[BatteryConfig, ...] = (),
    risk_policy: RiskPolicy = RiskPolicy.CHANCE_CONSTRAINED,
    confidence: float = 0.9,
    onsite_generation_mw: tuple[float, ...] | None = None,
    fatigue_limits: FatigueLimits | None = None,
) -> UncertainFlexibilityAssessment:
    if not scenarios or len({item.scenario_id for item in scenarios}) != len(scenarios):
        raise ValueError("uncertainty scenarios must be non-empty and unique")
    if onsite_generation_mw is not None and any(
        item.onsite_generation_mw != onsite_generation_mw for item in scenarios
    ):
        raise ValueError("scenario generation conflicts with supplied deterministic generation; specify one source")
    if not 0 < confidence < 1:
        raise ValueError("uncertainty confidence must be in (0, 1)")
    for scenario in scenarios:
        scenario.validate(len(intervals))
    probability = sum(item.probability for item in scenarios)
    if abs(probability - 1) > 1e-9:
        raise ValueError("scenario probabilities must sum to one")
    outcomes = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        result: FacilityOptimizationResult = optimize_facility_flexibility(
            requirement,
            intervals,
            facility,
            portfolio,
            profiles,
            replace(policy, battery_temperature_c=scenario.battery_temperature_c),
            economics,
            cooling=cooling,
            batteries=batteries,
            onsite_generation_mw=scenario.onsite_generation_mw,
            fatigue_limits=fatigue_limits,
        )
        assessment = result.assessment
        delivered = assessment.delivered_reduction_mw if assessment else 0.0
        shortfall = assessment.shortfall_mw if assessment else requirement.required_reduction_mw
        outcomes.append(ScenarioOutcome(
            scenario.scenario_id, scenario.probability, result.status, delivered, shortfall,
            result.objective_eur, result.model_fingerprint, accepted_optimization(result),
        ))
    feasible_probability = sum(
        item.probability for item in outcomes
        if item.physically_accepted and item.shortfall_mw <= 1e-9
    )
    expected_shortfall = sum(item.probability * item.shortfall_mw for item in outcomes)
    dependable = min((item.delivered_reduction_mw if item.physically_accepted else 0.0
                      for item in outcomes), default=0.0)
    if risk_policy == RiskPolicy.DISTRIBUTIONALLY_ROBUST:
        accepted = feasible_probability >= 1 - 1e-12
    elif risk_policy == RiskPolicy.CVAR:
        tail = sorted(outcomes, key=lambda item: item.shortfall_mw, reverse=True)
        mass = 0.0
        tail_shortfall = 0.0
        for item in tail:
            used = min(item.probability, max(0.0, 1 - confidence - mass))
            tail_shortfall += used * item.shortfall_mw
            mass += used
        accepted = tail_shortfall <= 1e-9
    else:
        accepted = feasible_probability + 1e-12 >= confidence
    blockers = () if accepted else ("uncertainty_risk_threshold",)
    encoded = json.dumps(
        {"requirement": requirement.requirement_id, "policy": risk_policy.value,
         "confidence": confidence, "scenarios": [asdict(item) for item in scenarios],
         "model_fingerprints": [item.model_fingerprint for item in outcomes]},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    return UncertainFlexibilityAssessment(
        risk_policy, confidence, tuple(outcomes), feasible_probability, expected_shortfall,
        max((item.shortfall_mw for item in outcomes), default=0.0), dependable, accepted,
        blockers, hashlib.sha256(encoded).hexdigest(),
    )
