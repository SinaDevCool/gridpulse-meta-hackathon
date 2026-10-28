"""Regression gates for solver truth, sparse assembly and immutable model identity."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.sparse import issparse

from capacity_backtest.data_center import optimizer
from capacity_backtest.data_center.solver_support import (
    constraint_matrix,
    feasible_incumbent,
    termination_status,
)

from .test_data_center_optimizer import inputs

pytestmark = pytest.mark.planning


@pytest.mark.parametrize("status, expected", [
    (0, "optimal"), (1, "limit_reached"), (2, "infeasible"),
    (3, "unbounded"), (4, "solver_error"), (99, "solver_error"),
])
def test_termination_does_not_conflate_timeout_with_infeasibility(status, expected):
    assert termination_status(status) == expected


def test_sparse_matrix_scales_with_nonzeros_not_cartesian_product():
    matrix = constraint_matrix([{999_999: 2.0}, {0: -1.0}], 1_000_000)
    assert issparse(matrix)
    assert matrix.nnz == 2
    assert matrix[0, 999_999] == 2.0


@pytest.mark.parametrize("value, accepted", [(1.0, True), (0.5, False), (2.0, False), (np.nan, False)])
def test_timeout_incumbent_must_be_integral_finite_and_feasible(value, accepted):
    solved = SimpleNamespace(status=1, x=np.array([value]), fun=1.0)
    assert feasible_incumbent(
        solved, constraint_matrix([{0: 1.0}], 1), [0], [1], [1], [1], [1]
    ) is accepted


def test_timeout_without_solution_never_runs_infeasibility_diagnostic(monkeypatch):
    calls = []

    def limited(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status=1, success=False, x=None, fun=None)

    monkeypatch.setattr(optimizer, "milp", limited)
    result = optimizer.optimize_facility_flexibility(**inputs())
    assert result.status == "limit_reached"
    assert result.solver_termination == "limit_reached"
    assert result.assessment is None
    assert result.actions == ()
    assert len(calls) == 1


def test_feasible_timeout_is_replayed_but_not_called_optimal(monkeypatch):
    actual = optimizer.milp

    def limited(*args, **kwargs):
        assert issparse(kwargs["constraints"].A)
        result = actual(*args, **kwargs)
        assert result.success
        result.status, result.success = 1, False
        result.mip_gap = 0.25
        return result

    monkeypatch.setattr(optimizer, "milp", limited)
    result = optimizer.optimize_facility_flexibility(**inputs())
    assert result.status == "feasible_not_proven_optimal"
    assert result.assessment is not None and result.assessment.feasible
    assert result.optimality_gap == 0.25
    assert result.automatic_live_dispatch_authorized is False


def test_physical_profiles_and_onsite_generation_change_model_fingerprint():
    values = inputs()
    first = optimizer.optimize_facility_flexibility(**values)
    profile = next(iter(values["profiles"].values()))
    changed = replace(profile, profile_id=profile.profile_id + "-revision")
    second = optimizer.optimize_facility_flexibility(
        **{**values, "profiles": {changed.workload_id: changed}}
    )
    third = optimizer.optimize_facility_flexibility(
        **values, onsite_generation_mw=(0.001,) * len(values["intervals"])
    )
    assert len({first.model_fingerprint, second.model_fingerprint, third.model_fingerprint}) == 3


def test_battery_modes_cannot_charge_and_discharge_simultaneously(monkeypatch):
    from capacity_backtest.phase2.battery import BatteryConfig

    actual = optimizer.milp
    captured = []

    def record(*args, **kwargs):
        result = actual(*args, **kwargs)
        captured.append((result, kwargs))
        return result

    monkeypatch.setattr(optimizer, "milp", record)
    result = optimizer.optimize_facility_flexibility(
        **inputs(), batteries=(BatteryConfig("battery", 0.1, 0.2, 0.2, 0.02, 0.18),)
    )
    assert result.status == "optimal"
    solved, request = captured[0]
    # Existing fixture has two workload profile options per interval; each
    # battery interval adds charge, discharge, stored energy, and binary mode.
    offset = 2 * len(inputs()["intervals"])
    for index in range(len(inputs()["intervals"])):
        start = offset + 4 * index
        assert request["integrality"][start + 3] == 1
        assert min(solved.x[start], solved.x[start + 1]) <= 1e-8


def test_objective_prices_facility_meter_energy_including_battery_charging():
    from capacity_backtest.phase2.battery import BatteryConfig

    values = inputs()
    result = optimizer.optimize_facility_flexibility(
        **values, batteries=(BatteryConfig("battery", 0.1, 0.2, 0.2, 0.02, 0.18),)
    )
    assert result.status == "optimal"
    assert result.facility is not None
    duration = values["intervals"][0].duration_minutes / 60
    expected = sum(
        point.grid_import_mw * price * duration
        for point, price in zip(
            result.facility.points, values["economics"].import_price_eur_per_mwh
        )
    )
    assert result.objective_eur == pytest.approx(expected, abs=1e-7)


def test_nonzero_cooling_factor_matches_physical_replay():
    values = inputs()
    values["facility"] = replace(values["facility"], cooling_load_factor=0.3)
    result = optimizer.optimize_facility_flexibility(**values)
    assert result.status == "optimal"
    assert result.facility is not None
    assert result.assessment is not None and result.assessment.feasible
    duration = values["intervals"][0].duration_minutes / 60
    expected = sum(
        point.grid_import_mw * price * duration
        for point, price in zip(
            result.facility.points, values["economics"].import_price_eur_per_mwh
        )
    )
    assert result.objective_eur == pytest.approx(expected, abs=1e-7)


def test_mixed_duration_horizon_is_rejected_instead_of_using_first_duration():
    values = inputs()
    intervals = values["intervals"]
    values["intervals"] = (*intervals[:-1], replace(intervals[-1], duration_minutes=30))
    with pytest.raises(ValueError, match="uniform"):
        optimizer.optimize_facility_flexibility(**values)
