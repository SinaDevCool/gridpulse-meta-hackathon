from __future__ import annotations

from dataclasses import replace

import pytest

from capacity_backtest.contracts import TruthClass
from capacity_backtest.domain import CapacityEnvelopeResult, StudyHorizon
from capacity_backtest.phase1.horizons import DEFAULT_HORIZONS, MultiHorizonStudy

from .test_phase0_domain import provenance, scenario


def scenarios():
    return {
        horizon: replace(scenario(), scenario_id=f"scenario-{horizon.value}", horizon=horizon)
        for horizon in StudyHorizon
    }


def runner(item):
    return CapacityEnvelopeResult(
        result_id=f"result-{item.horizon.value}",
        scenario_id=item.scenario_id,
        truth_class=TruthClass.SYNTHETIC_BENCHMARK,
        firm_capacity_mw=40,
        conditional_capacity_mw=45,
        activatable_capacity_mw=45,
        confidence_level=0.9,
        binding_constraint="n-1",
        unknown_constraints=("operator validation",),
        capacity_claim=False,
        provenance=provenance(),
    )


def test_multi_horizon_study_requires_distinct_uncertainty_contracts() -> None:
    counts = {
        StudyHorizon.DAY_AHEAD: 24,
        StudyHorizon.WEEK_AHEAD: 168,
        StudyHorizon.SEASONAL: 12,
        StudyHorizon.CONNECTION_PLANNING: 4,
    }
    quantiles = {horizon: spec.required_quantiles for horizon, spec in DEFAULT_HORIZONS.items()}
    result = MultiHorizonStudy().run(scenarios(), counts, quantiles, runner)
    assert result.consistent_scenario_family
    assert set(result.results) == set(StudyHorizon)
    assert len({spec.uncertainty_model for spec in DEFAULT_HORIZONS.values()}) == 4


def test_multi_horizon_study_rejects_stretched_hourly_configuration() -> None:
    counts = {horizon: 24 for horizon in StudyHorizon}
    quantiles = {horizon: spec.required_quantiles for horizon, spec in DEFAULT_HORIZONS.items()}
    with pytest.raises(ValueError, match="point count"):
        MultiHorizonStudy().run(scenarios(), counts, quantiles, runner)
