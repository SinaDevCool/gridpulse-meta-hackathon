from capacity_backtest.data_center.contracts import PlanningInterval, validate_intervals
from capacity_backtest.phase2.thermal_workload import (
    CoolingConfig,
    WorkloadConfig,
    simulate_cooling_workload,
)


def test_hourly_and_quarter_hour_energy_balances_are_equivalent() -> None:
    cooling = CoolingConfig(4, 0, 0, maximum_thermal_debt_mwh=0)
    workload = WorkloadConfig(4, 4, deadline_hours=2)
    hourly = simulate_cooling_workload([4, 0], [0, 4], cooling, workload)
    quarter = simulate_cooling_workload(
        [4, 4, 4, 4, 0, 0, 0, 0],
        [0, 0, 0, 0, 4, 4, 4, 4],
        cooling,
        workload,
        interval_hours=0.25,
    )
    assert hourly.ending_workload_backlog_mwh == quarter.ending_workload_backlog_mwh == 0
    assert sum(p.workload_shift_mw for p in quarter.points) * 0.25 == 4
    assert sum(p.workload_recovery_mw for p in quarter.points) * 0.25 == 4


def test_planning_intervals_require_contiguous_supported_resolution() -> None:
    intervals = (
        PlanningInterval(0, "2026-01-01T00:00:00+00:00", 15),
        PlanningInterval(1, "2026-01-01T00:15:00+00:00", 15),
    )
    validate_intervals(intervals)
