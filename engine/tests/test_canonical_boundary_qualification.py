"""Known-answer gates for previously ignored canonical inputs; never runs locally."""
from dataclasses import asdict, replace

import pytest

from capacity_backtest.application.facility import parse_facility_plan_request, run_facility_plan
from capacity_backtest.data_center.optimizer import optimize_facility_flexibility
from capacity_backtest.phase2.battery import BatteryConfig, BatteryRequest, simulate_battery

from .test_application_facility import request
from .test_data_center_optimizer import inputs

pytestmark = pytest.mark.planning


def test_battery_and_generation_reach_the_sole_optimizer():
    payload = request()
    battery = BatteryConfig("battery", 0.1, 0.2, 0.2, 0.02, 0.18)
    payload["batteries"] = [asdict(battery)]
    payload["onsite_generation_mw"] = [0.001] * len(payload["intervals"])
    parsed = parse_facility_plan_request(payload)
    assert parsed["batteries"] == (battery,)
    assert parsed["onsite_generation_mw"] == (0.001,) * len(payload["intervals"])
    result = run_facility_plan(payload)
    assert result["result"]["status"] == "optimal"
    assert len(result["result"]["battery_requests"]) == len(payload["intervals"])


def test_unknown_inputs_cannot_be_silently_ignored():
    payload = request()
    payload["ignored_battery_settings"] = {}
    with pytest.raises(ValueError, match="unsupported facility-plan fields"):
        parse_facility_plan_request(payload)


def test_duplicate_profiles_cannot_overwrite_each_other():
    payload = request()
    payload["profiles"].append(payload["profiles"][0])
    with pytest.raises(ValueError, match="duplicate"):
        parse_facility_plan_request(payload)


def test_quarter_hour_single_interval_replay_uses_explicit_duration():
    battery = BatteryConfig("battery", 1, 10, 5, 0, 0, discharge_efficiency=1)
    result = simulate_battery(battery, [BatteryRequest("2026-01-01T00:00:00Z", 1)], interval_hours=0.25)
    assert result.ending_soc_mwh == pytest.approx(4.75)


def test_charge_limit_and_soc_ceiling_are_not_discharge_limit():
    battery = BatteryConfig("battery", 1, 10, 5, 0, 0, charge_efficiency=1,
                            maximum_charge_power_mw=0.2, maximum_soc_fraction=0.6)
    result = simulate_battery(battery, [BatteryRequest("2026-01-01T00:00:00Z", -1)], interval_hours=0.25)
    assert result.ending_soc_mwh == pytest.approx(5.05)
    assert result.points[0].delivered_power_mw == pytest.approx(-0.2)


def test_backup_energy_is_protected_in_replay():
    battery = BatteryConfig("battery", 10, 10, 5, 0, 0, discharge_efficiency=1,
                            critical_load_mw=4, backup_autonomy_minutes=60)
    result = simulate_battery(battery, [BatteryRequest("2026-01-01T00:00:00Z", 10)], interval_hours=1)
    assert result.ending_soc_mwh == pytest.approx(4)
    assert result.points[0].delivered_power_mw == pytest.approx(1)


def test_impossible_gpu_capacity_is_not_an_accepted_plan():
    values = inputs()
    values["portfolio"] = replace(values["portfolio"], fleet_gpu_capacity=1)
    result = optimize_facility_flexibility(**values)
    assert result.status == "infeasible"
    assert result.assessment is None


def test_self_discharge_first_interval_agrees_with_replay():
    values = inputs()
    battery = BatteryConfig("battery", 0.1, 0.2, 0.2, 0.02, 0.18,
                            self_discharge_fraction_per_hour=0.001)
    result = optimize_facility_flexibility(**values, batteries=(battery,))
    assert result.status == "optimal"
    assert result.assessment.battery_terminal_targets_met


def test_transport_and_direct_solver_produce_identical_joint_result():
    payload = request()
    payload["batteries"] = [asdict(BatteryConfig("battery", 0.1, 0.2, 0.2, 0.02, 0.18,
                                               maximum_charge_power_mw=0.025))]
    payload["onsite_generation_mw"] = [0.001] * len(payload["intervals"])
    payload["fleet_gpu_capacity"] = 8
    direct = optimize_facility_flexibility(**parse_facility_plan_request(payload))
    transported = run_facility_plan(payload)["result"]
    assert direct.status == transported["status"] == "optimal"
    assert direct.model_fingerprint == transported["model_fingerprint"]
    assert transported["objective_eur"] == pytest.approx(direct.objective_eur)
    assert len(transported["battery_trajectories"]) == 1
    assert transported["battery_trajectories"][0]["resource_id"] == "battery"
    for actual, serialized in zip(direct.facility.points, transported["facility"]["points"]):
        assert serialized["grid_import_mw"] == pytest.approx(actual.grid_import_mw)


def test_generation_reduces_meter_import_and_cost_not_just_fingerprint():
    values = inputs(required=0)
    baseline = optimize_facility_flexibility(**values)
    generated = optimize_facility_flexibility(**values, onsite_generation_mw=(0.001,) * 4)
    assert baseline.status == generated.status == "optimal"
    assert baseline.actions == generated.actions
    for before, after in zip(baseline.facility.points, generated.facility.points):
        assert before.grid_import_mw - after.grid_import_mw == pytest.approx(0.001)
    assert baseline.objective_eur - generated.objective_eur == pytest.approx(
        sum(values["economics"].import_price_eur_per_mwh) * 0.001
    )


def test_shared_gpu_fleet_schedules_two_jobs_without_double_booking():
    values = inputs(required=0)
    first = replace(values["portfolio"].workloads[0], expected_duration_minutes=120)
    second = replace(first, workload_id="job-2")
    values["portfolio"] = replace(values["portfolio"], workloads=(first, second), fleet_gpu_capacity=8)
    first_profile = values["profiles"][first.workload_id]
    values["profiles"] = {first.workload_id: first_profile,
                          second.workload_id: replace(first_profile, workload_id=second.workload_id)}
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal"
    assert not result.portfolio.sla_violations
    for index in range(4):
        allocated = sum(job.points[index].gpu_count for job in result.portfolio.workload_trajectories
                        if job.points[index].power_mw > 1e-9)
        assert allocated <= 8
    assert all(job.deadline_met for job in result.portfolio.workload_trajectories)


def test_asymmetric_charging_is_enforced_by_optimizer_and_replay():
    values = inputs()
    battery = BatteryConfig("battery", 0.1, 0.2, 0.2, 0.02, 0.18, maximum_charge_power_mw=0.005)
    result = optimize_facility_flexibility(**values, batteries=(battery,))
    assert result.status == "optimal"
    assert all(point.power_mw >= -0.005 - 1e-9 for point in result.battery_requests)
    assert result.battery_trajectories[0].shortfall_mwh < 1e-8
    assert result.battery_trajectories[0].terminal_target_met


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_generation_never_enters_solver(value):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        optimize_facility_flexibility(**inputs(), onsite_generation_mw=(value,) * 4)
