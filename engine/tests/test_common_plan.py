from dataclasses import replace

import pytest

from capacity_backtest.data_center.common_plan import optimize_common_plan
from capacity_backtest.data_center.optimizer import optimize_facility_flexibility
from capacity_backtest.data_center.uncertainty import ScenarioBounds, UncertaintyScenario
from capacity_backtest.phase2.battery import BatteryConfig

from .test_data_center_optimizer import inputs


def scenarios():
    return (UncertaintyScenario("base", .5, (20.,) * 4, (0.,) * 4),
            UncertaintyScenario("generation", .5, (30.,) * 4, (.01,) * 4))


def test_shared_commands_are_replayed_in_every_scenario():
    values = inputs()
    values["policy"] = replace(values["policy"], solver_time_limit_seconds=5)
    values["batteries"] = (BatteryConfig("battery", .1, .2, .2, .02, .18),)
    result = optimize_common_plan(values, scenarios())
    assert result["accepted"] and result["common_plan_validated"]
    a, b = [item["result"] for item in result["outcomes"]]
    assert a.actions == b.actions
    assert a.battery_requests
    assert [(p.power_mw, p.operating_mode) for p in a.battery_requests] == [(p.power_mw, p.operating_mode) for p in b.battery_requests]
    assert a.battery_requests[0].temperature_c != b.battery_requests[0].temperature_c
    assert a.cooling_adjustment_mw == b.cooling_adjustment_mw
    assert result["scenario_weights_basis"] == "assumed_not_calibrated_probability"
    assert a.optimality_gap is None  # No per-scenario optimality claim.


def test_single_scenario_matches_canonical_objective_and_replay():
    values = inputs()
    values["policy"] = replace(values["policy"], solver_time_limit_seconds=5)
    scenario = UncertaintyScenario("only", 1., values["policy"].battery_temperature_c, (0.,) * 4)
    result = optimize_common_plan(values, (scenario,))
    direct = optimize_facility_flexibility(**values)
    assert result["accepted"]
    assert result["outcomes"][0]["result"].objective_eur == pytest.approx(direct.objective_eur)


def test_common_plan_bounds_and_nonfinite_scenarios_fail_closed():
    values = inputs()
    values["policy"] = replace(values["policy"], solver_time_limit_seconds=5)
    with pytest.raises(ValueError, match="unique"):
        optimize_common_plan(values, scenarios() * 3)
    values["policy"] = replace(values["policy"], maximum_variables=1)
    with pytest.raises(ValueError, match="budget"):
        optimize_common_plan(values, scenarios())
    with pytest.raises(ValueError, match="finite"):
        ScenarioBounds(float("nan"), 30, 0, 1).validate()
    with pytest.raises(ValueError, match="finite"):
        UncertaintyScenario("bad", 1, (float("nan"),), (0,)).validate(1)
