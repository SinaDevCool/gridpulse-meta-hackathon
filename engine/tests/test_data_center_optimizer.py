from dataclasses import replace

from capacity_backtest.data_center.contracts import (
    FacilityOptimizationPolicy,
    FlexibilityEconomics,
)
from capacity_backtest.data_center.optimizer import optimize_facility_flexibility
from capacity_backtest.data_center.portfolio import WorkloadPortfolio
from capacity_backtest.phase2.battery import BatteryConfig
from capacity_backtest.phase2.fatigue import FatigueLimits
from capacity_backtest.phase2.thermal_workload import CoolingConfig

from .test_data_center_contracts import workload
from .test_data_center_facility import config
from .test_data_center_flexibility_assessment import requirement
from .test_data_center_power_profiles import profile
from .test_data_center_workloads import INTERVALS


def inputs(required: float = 0.03):
    job = workload()
    return {
        "requirement": requirement(required=required),
        "intervals": INTERVALS,
        "facility": config(),
        "portfolio": WorkloadPortfolio("portfolio", (job,)),
        "profiles": {job.workload_id: profile()},
        "policy": FacilityOptimizationPolicy((True, False, False, False), (20.0, 20.0, 20.0, 20.0)),
        "economics": FlexibilityEconomics((100.0, 10.0, 10.0, 10.0)),
        "cooling": CoolingConfig(0.02, 0.0, 0.0),
    }


def test_optimizer_produces_replay_verified_schedule_deterministically() -> None:
    first = optimize_facility_flexibility(**inputs())
    second = optimize_facility_flexibility(**inputs())
    assert first.status == "optimal"
    assert first.assessment is not None and first.assessment.feasible
    assert first.model_fingerprint == second.model_fingerprint
    assert first.actions == second.actions
    assert first.objective_eur == second.objective_eur
    assert first.automatic_live_dispatch_authorized is False


def test_infeasible_requirement_returns_diagnostic_slack_not_a_schedule() -> None:
    result = optimize_facility_flexibility(**inputs(required=0.5))
    assert result.status == "infeasible"
    assert result.assessment is None
    assert result.diagnostics
    assert result.automatic_live_dispatch_authorized is False


def test_battery_schedule_replays_soc_and_terminal_target() -> None:
    values = inputs(required=0.03)
    battery = BatteryConfig("battery", 0.1, 0.2, 0.2, 0.02, 0.18)
    result = optimize_facility_flexibility(**values, batteries=(battery,))
    assert result.status == "optimal"
    assert len(result.battery_requests) == len(INTERVALS)
    assert result.assessment is not None and result.assessment.battery_terminal_targets_met


def test_hard_physics_are_unchanged_by_low_prices() -> None:
    values = inputs()
    values["economics"] = FlexibilityEconomics((0.0, 0.0, 0.0, 0.0))
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal"
    assert result.facility is not None
    assert result.facility.import_limit_violation_count == 0


def test_fatigue_failure_is_not_promoted_to_feasible() -> None:
    result = optimize_facility_flexibility(
        **inputs(),
        fatigue_limits=FatigueLimits(0, 0, 0, 0, 0, 0),
    )
    assert result.status == "replay_failed"
    assert result.fatigue is not None and not result.fatigue.passed


def test_policy_horizon_mismatch_fails_closed() -> None:
    values = inputs()
    values["policy"] = replace(values["policy"], battery_temperature_c=(20.0,))
    try:
        optimize_facility_flexibility(**values)
    except ValueError as exc:
        assert "temperatures" in str(exc)
    else:
        raise AssertionError("invalid policy must fail closed")


def test_interval_import_envelope_is_enforced_in_solver_and_replay():
    values = inputs(required=0)
    limits = (0.5, 0.4, 0.5, 0.5)
    values["facility"] = replace(values["facility"], import_limit_profile_mw=limits)
    result = optimize_facility_flexibility(**values)
    assert result.assessment is not None and result.assessment.feasible
    assert all(p.grid_import_mw <= limit + 1e-7 for p, limit in zip(result.facility.points, limits))


def test_interval_import_envelope_rejects_mismatched_horizon():
    import pytest

    values = inputs()
    values["facility"] = replace(values["facility"], import_limit_profile_mw=(0.1,))
    with pytest.raises(ValueError):
        optimize_facility_flexibility(**values)


def test_zero_interval_envelope_cannot_return_an_accepted_plan():
    values = inputs(required=0)
    values["facility"] = replace(values["facility"], import_limit_profile_mw=(0.0,) * 4)
    result = optimize_facility_flexibility(**values)
    assert result.assessment is None
    assert result.status == "infeasible"
