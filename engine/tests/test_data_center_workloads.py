import pytest

from capacity_backtest.data_center.contracts import (
    PlanningInterval,
    ScheduledWorkloadAction,
    WorkloadActionKind,
    WorkloadKind,
    WorkloadSLA,
)
from capacity_backtest.data_center.workloads import simulate_workload

from .test_data_center_contracts import workload
from .test_data_center_power_profiles import profile

INTERVALS = tuple(
    PlanningInterval(i, f"2026-01-01T0{i}:00:00+00:00", 60) for i in range(4)
)


def test_checkpoint_and_restart_overhead_are_non_productive() -> None:
    actions = (
        ScheduledWorkloadAction("pause", "job-1", 1, WorkloadActionKind.CHECKPOINT_AND_PAUSE),
        ScheduledWorkloadAction("resume", "job-1", 2, WorkloadActionKind.RESUME),
    )
    result = simulate_workload(
        workload(expected_duration_minutes=180),
        profile(),
        INTERVALS,
        actions,
        initial_site_id="site-a",
    )
    assert result.points[1].checkpoint_or_restart
    assert result.points[1].completed_work_hours == 0
    assert result.pause_count == 1


def test_gpu_power_and_transition_bounds_fail_closed() -> None:
    bad_gpu = (ScheduledWorkloadAction("gpu", "job-1", 0, WorkloadActionKind.REDUCE_GPU_ALLOCATION, target_gpu_count=2),)
    with pytest.raises(ValueError, match="GPU action"):
        simulate_workload(workload(), profile(), INTERVALS, bad_gpu, initial_site_id="site-a")
    resume = (ScheduledWorkloadAction("resume", "job-1", 0, WorkloadActionKind.RESUME),)
    with pytest.raises(ValueError, match="paused"):
        simulate_workload(workload(), profile(), INTERVALS, resume, initial_site_id="site-a")


def test_critical_workload_cannot_receive_flexibility_action() -> None:
    critical = workload(
        workload_kind=WorkloadKind.CRITICAL_INFERENCE,
        minimum_gpu_count=8,
        sla=WorkloadSLA("2026-01-01T04:00:00+00:00", 0, 1, 0, 100, 1000),
    )
    action = (
        ScheduledWorkloadAction(
            "cap", "job-1", 0, WorkloadActionKind.POWER_CAP, target_power_cap_mw=0.04
        ),
    )
    with pytest.raises(ValueError, match="critical workloads"):
        simulate_workload(critical, profile(), INTERVALS, action, initial_site_id="site-a")
