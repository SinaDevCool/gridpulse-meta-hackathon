from dataclasses import replace

import pytest

from capacity_backtest.data_center.contracts import PlanningInterval, WorkloadActionKind
from capacity_backtest.data_center.optimizer import optimize_facility_flexibility

from .test_data_center_optimizer import inputs

pytestmark = pytest.mark.planning


def case(mode):
    values = inputs(required=0.08)
    job = values["portfolio"].workloads[0]
    job = replace(job, expected_duration_minutes=180, maximum_start_delay_minutes=0,
                  checkpoint_duration_minutes=60, restart_duration_minutes=60, execution_mode=mode,
                  sla=replace(job.sla, deadline="2026-01-01T06:00:00+00:00",
                              minimum_throughput_fraction=1, maximum_slowdown_fraction=0, maximum_pauses=1))
    values["portfolio"] = replace(values["portfolio"], workloads=(job,), fleet_gpu_capacity=8)
    values["intervals"] = tuple(PlanningInterval(i, f"2026-01-01T0{i}:00:00+00:00", 60) for i in range(6))
    values["policy"] = replace(values["policy"], event_intervals=(False, False, True, False, False, False),
                               battery_temperature_c=(20.0,) * 6)
    values["economics"] = replace(values["economics"], import_price_eur_per_mwh=(100.0,) + (10.0,) * 5)
    return values


def test_checkpoint_plan_meets_event_that_uninterrupted_job_cannot():
    uninterrupted = optimize_facility_flexibility(**case("uninterrupted"))
    assert uninterrupted.status == "infeasible"
    result = optimize_facility_flexibility(**case("checkpointable"))
    assert result.status == "optimal", result.diagnostics
    assert result.assessment.feasible
    kinds = [action.action_kind for action in result.actions]
    assert kinds.count(WorkloadActionKind.CHECKPOINT_AND_PAUSE) == 1
    assert kinds.count(WorkloadActionKind.RESUME) == 1
    trajectory = result.portfolio.workload_trajectories[0]
    assert trajectory.deadline_met
    assert trajectory.pause_count == 1
    assert sum(point.completed_work_hours for point in trajectory.points) == pytest.approx(3)
    overhead = [point for point in trajectory.points if point.checkpoint_or_restart]
    assert len(overhead) == 2
    assert all(point.completed_work_hours == 0 and point.power_mw > 0 for point in overhead)


def test_checkpoint_power_reconciles_with_idle_fleet_accounting():
    values = case("checkpointable")
    values["portfolio"] = replace(values["portfolio"], idle_gpu_power_watts=70)
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal", result.diagnostics
    assert result.assessment.recovery_complete


def test_checkpoint_mode_cannot_invent_pause_permission():
    values = case("checkpointable")
    job = values["portfolio"].workloads[0]
    replace(job, sla=replace(job.sla, maximum_pauses=0))
    with pytest.raises(ValueError, match="pause permission"):
        replace(job, sla=replace(job.sla, maximum_pauses=0)).validate()


@pytest.mark.parametrize("state,overhead", [("paused", 0), ("checkpointing", 60), ("restarting", 60)])
def test_carried_checkpoint_state_preserves_work_and_pause_budget(state, overhead):
    values = case("checkpointable")
    job = values["portfolio"].workloads[0]
    job = replace(job, remaining_work_minutes=60, initial_execution_state=state,
                  initial_overhead_remaining_minutes=overhead, initial_pause_count=1)
    values["portfolio"] = replace(values["portfolio"], workloads=(job,))
    values["requirement"] = replace(values["requirement"], required_reduction_mw=0,
                                    conservative_required_reduction_mw=0,
                                    firm_limit_mw=values["requirement"].requested_import_mw)
    values["policy"] = replace(values["policy"], event_intervals=(False,) * 6)
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal", result.diagnostics
    trajectory = result.portfolio.workload_trajectories[0]
    assert trajectory.pause_count == 1
    assert sum(p.completed_work_hours for p in trajectory.points) == pytest.approx(1)
    assert trajectory.deadline_met
    if overhead:
        assert trajectory.points[0].checkpoint_or_restart
        assert trajectory.points[0].completed_work_hours == 0
