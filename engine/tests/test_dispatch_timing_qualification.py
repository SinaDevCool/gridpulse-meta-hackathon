from dataclasses import replace

import pytest

from capacity_backtest.data_center.optimizer import optimize_facility_flexibility
from capacity_backtest.phase2.battery import BatteryConfig, BatteryRequest, simulate_battery
from capacity_backtest.phase2.fatigue import FatigueLimits, evaluate_fatigue
from .test_data_center_optimizer import inputs

pytestmark = pytest.mark.planning


def test_subhourly_fatigue_measures_hours_and_energy_not_samples():
    limits = FatigueLimits(1, 1, 10, 1, 10, 0)
    result = evaluate_fatigue([1, 1, 1, 1], 0, limits, interval_hours=0.25)
    assert result.passed
    assert result.event_hours == 1
    assert result.maximum_consecutive_hours == 1
    assert result.shifted_energy_mwh == 1


def test_battery_replay_rejects_ramp_violation():
    battery = BatteryConfig("b", 10, 20, 10, 0, 0, ramp_rate_mw_per_minute=0.01)
    with pytest.raises(ValueError, match="ramp"):
        simulate_battery(battery, [BatteryRequest("2026-01-01T00:00:00Z", 5)], interval_hours=0.25)


def test_milp_ramp_matches_replayed_dispatch():
    battery = BatteryConfig("b", 0.1, 0.2, 0.2, 0.02, 0.18, ramp_rate_mw_per_minute=0.0001)
    result = optimize_facility_flexibility(**inputs(), batteries=(battery,))
    assert result.status == "optimal"
    previous = 0.0
    for point in result.battery_trajectories[0].points:
        assert abs(point.delivered_power_mw - previous) <= 0.006 + 1e-8
        previous = point.delivered_power_mw


def test_maximum_start_delay_cannot_be_evaded_by_expensive_first_interval():
    values = inputs(required=0)
    job = replace(values["portfolio"].workloads[0], maximum_start_delay_minutes=0)
    values["portfolio"] = replace(values["portfolio"], workloads=(job,))
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal"
    assert result.portfolio.workload_trajectories[0].points[0].power_mw > 0


def test_initially_running_job_uses_remaining_work_and_cannot_delay_start():
    values = inputs(required=0)
    job = replace(values["portfolio"].workloads[0], initially_running=True,
                  expected_duration_minutes=180, remaining_work_minutes=60)
    values["portfolio"] = replace(values["portfolio"], workloads=(job,))
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal"
    trajectory = result.portfolio.workload_trajectories[0]
    assert trajectory.points[0].power_mw > 0
    assert trajectory.ending_remaining_work_hours == 0
    assert sum(point.completed_work_hours for point in trajectory.points) == pytest.approx(1)


def test_dwell_replay_preserves_direction_during_idle_intervals():
    battery = BatteryConfig("b", 1, 10, 5, 0, 0, minimum_dwell_minutes=60)
    requests = [BatteryRequest("2026-01-01T00:00:00Z", 0.1),
                BatteryRequest("2026-01-01T00:15:00Z", 0),
                BatteryRequest("2026-01-01T00:30:00Z", -0.1)]
    with pytest.raises(ValueError, match="dwell"):
        simulate_battery(battery, requests, interval_hours=0.25)


def test_optimizer_mode_dwell_replays_with_initial_state():
    battery = BatteryConfig("b", 0.1, 0.2, 0.2, 0.02, 0.18,
                            minimum_dwell_minutes=120, initial_mode="discharge", initial_mode_minutes=60)
    result = optimize_facility_flexibility(**inputs(), batteries=(battery,))
    assert result.status == "optimal"
    assert result.battery_trajectories[0].shortfall_mwh < 1e-8


def test_operating_target_is_enforced_separately_from_contract_limit():
    values = inputs(required=0)
    values["policy"] = replace(values["policy"], operating_target_mw=0.12)
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal"
    assert max(point.grid_import_mw for point in result.facility.points) <= 0.12 + 1e-8


def test_timestamp_availability_is_shared_by_milp_and_replay():
    battery = BatteryConfig("b", 0.1, 0.2, 0.2, 0.02, 0.18,
                            unavailable_at=("2026-01-01T00:00:00Z",))
    result = optimize_facility_flexibility(**inputs(), batteries=(battery,))
    assert result.status == "optimal"
    assert result.battery_requests[0].power_mw == pytest.approx(0)
    assert not result.battery_trajectories[0].points[0].availability


def test_idle_fleet_draw_is_counted_once_and_matches_replay():
    values = inputs(required=0)
    values["portfolio"] = replace(values["portfolio"], fleet_gpu_capacity=16, idle_gpu_power_watts=70)
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal"
    for interval in values["intervals"]:
        index = interval.index
        jobs = result.portfolio.workload_trajectories
        active = sum(job.points[index].gpu_count for job in jobs if job.points[index].power_mw > 1e-9)
        expected = sum(job.points[index].power_mw for job in jobs) + (16 - active) * 70 / 1_000_000
        assert result.facility.points[index].it_power_mw == pytest.approx(expected)


def test_zero_shift_fraction_does_not_offer_workload_curtailment():
    values = inputs(required=0.03)
    values["policy"] = replace(values["policy"], maximum_workload_reduction_fraction=0)
    result = optimize_facility_flexibility(**values)
    assert result.status == "infeasible"
