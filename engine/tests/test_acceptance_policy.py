from dataclasses import replace

import pytest

from capacity_backtest.application.facility import ENGINE_VERSION
from capacity_backtest import __version__
from capacity_backtest.data_center.acceptance import accepted_optimization
from capacity_backtest.data_center.optimizer import optimize_facility_flexibility
from .test_data_center_optimizer import inputs

pytestmark = pytest.mark.planning


def test_single_package_version_identifies_engine():
    assert ENGINE_VERSION == f"gridpulse-capacity-backtest-{__version__}"


def test_feasible_incumbent_policy_requires_physical_replay():
    result = optimize_facility_flexibility(**inputs())
    assert accepted_optimization(result)
    feasible = replace(result, status="feasible_not_proven_optimal")
    assert accepted_optimization(feasible)
    assert not accepted_optimization(feasible, allow_feasible_incumbent=False)
    assert not accepted_optimization(replace(feasible, assessment=None))
    assert not accepted_optimization(replace(result, status="replay_failed"))


def test_variable_guard_rejects_before_solver(monkeypatch):
    values = inputs()
    values["policy"] = replace(values["policy"], maximum_variables=1)
    from capacity_backtest.data_center import optimizer
    monkeypatch.setattr(optimizer, "milp", lambda *args, **kwargs: pytest.fail("solver must not run"))
    with pytest.raises(ValueError, match="before model allocation"):
        optimize_facility_flexibility(**values)
