import pytest

from capacity_backtest.data_center.uncertainty import (
    ScenarioBounds,
    UncertaintyScenario,
    evaluate_uncertain_flexibility,
    generate_uncertainty_scenarios,
)
from capacity_backtest.phase1.risk import RiskPolicy

from .test_data_center_optimizer import inputs


def scenarios():
    return (
        UncertaintyScenario("base", 0.8, (20.0,) * 4, (0.0,) * 4),
        UncertaintyScenario("hot", 0.2, (40.0,) * 4, (0.0,) * 4),
    )


def test_uncertainty_is_deterministic_and_risk_governed() -> None:
    values = inputs()
    first = evaluate_uncertain_flexibility(**values, scenarios=scenarios())
    second = evaluate_uncertain_flexibility(**values, scenarios=scenarios())
    assert first == second
    assert first.accepted and not first.capacity_claim
    robust = evaluate_uncertain_flexibility(
        **values, scenarios=scenarios(), risk_policy=RiskPolicy.DISTRIBUTIONALLY_ROBUST
    )
    assert robust.feasibility_probability == 1 and robust.accepted


def test_uncertainty_probability_fails_closed() -> None:
    with pytest.raises(ValueError, match="sum to one"):
        evaluate_uncertain_flexibility(
            **inputs(), scenarios=(UncertaintyScenario("bad", 0.5, (20.0,) * 4, (0.0,) * 4),)
        )


def test_seeded_scenario_generation_is_bounded_and_reproducible() -> None:
    bounds = ScenarioBounds(0, 40, 0, 0.1)
    first = generate_uncertainty_scenarios(bounds, horizon_size=4, count=10, seed=7)
    second = generate_uncertainty_scenarios(bounds, horizon_size=4, count=10, seed=7)
    assert first == second
    assert sum(item.probability for item in first) == pytest.approx(1)
