"""One contract for day-ahead, week-ahead, seasonal, and planning studies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from capacity_backtest.domain import CapacityEnvelopeResult, StudyHorizon, StudyScenario


@dataclass(frozen=True)
class HorizonSpecification:
    horizon: StudyHorizon
    minimum_points: int
    maximum_points: int
    required_quantiles: tuple[float, ...]
    uncertainty_model: str

    def validate(self) -> None:
        if self.minimum_points <= 0 or self.maximum_points < self.minimum_points:
            raise ValueError("invalid horizon point limits")
        if not self.required_quantiles or any(not 0 < value < 1 for value in self.required_quantiles):
            raise ValueError("horizon quantiles must lie in (0, 1)")
        if not self.uncertainty_model:
            raise ValueError("horizon requires an uncertainty model")


DEFAULT_HORIZONS = {
    StudyHorizon.DAY_AHEAD: HorizonSpecification(StudyHorizon.DAY_AHEAD, 24, 48, (0.1, 0.5, 0.9), "hourly-weather-workload-v1"),
    StudyHorizon.WEEK_AHEAD: HorizonSpecification(StudyHorizon.WEEK_AHEAD, 168, 336, (0.1, 0.5, 0.9), "weekly-regime-v1"),
    StudyHorizon.SEASONAL: HorizonSpecification(StudyHorizon.SEASONAL, 12, 744, (0.05, 0.5, 0.95), "seasonal-stress-v1"),
    StudyHorizon.CONNECTION_PLANNING: HorizonSpecification(StudyHorizon.CONNECTION_PLANNING, 4, 120, (0.05, 0.5, 0.95), "planning-scenario-v1"),
}


@dataclass(frozen=True)
class MultiHorizonResult:
    results: dict[StudyHorizon, CapacityEnvelopeResult]
    consistent_scenario_family: bool


class MultiHorizonStudy:
    def __init__(self, specifications: dict[StudyHorizon, HorizonSpecification] | None = None):
        self.specifications = specifications or DEFAULT_HORIZONS
        if set(self.specifications) != set(StudyHorizon):
            raise ValueError("multi-horizon study requires every supported horizon")
        for specification in self.specifications.values():
            specification.validate()

    def run(
        self,
        scenarios: dict[StudyHorizon, StudyScenario],
        point_counts: dict[StudyHorizon, int],
        quantiles: dict[StudyHorizon, tuple[float, ...]],
        runner: Callable[[StudyScenario], CapacityEnvelopeResult],
    ) -> MultiHorizonResult:
        if set(scenarios) != set(StudyHorizon):
            raise ValueError("one scenario is required for every horizon")
        family = None
        results = {}
        for horizon in StudyHorizon:
            scenario = scenarios[horizon]
            scenario.validate()
            if scenario.horizon != horizon:
                raise ValueError("scenario horizon does not match its study slot")
            specification = self.specifications[horizon]
            count = point_counts.get(horizon, 0)
            if not specification.minimum_points <= count <= specification.maximum_points:
                raise ValueError(f"{horizon.value} point count is outside its allowed range")
            supplied = set(quantiles.get(horizon, ()))
            if not set(specification.required_quantiles) <= supplied:
                raise ValueError(f"{horizon.value} is missing required forecast quantiles")
            identity = (scenario.network_model_id, scenario.candidate_bus_id, scenario.assumption_set_id)
            family = identity if family is None else family
            if identity != family:
                raise ValueError("multi-horizon scenarios must describe one scenario family")
            result = runner(scenario)
            result.validate()
            if result.scenario_id != scenario.scenario_id:
                raise ValueError("multi-horizon result identity mismatch")
            results[horizon] = result
        return MultiHorizonResult(results, True)
