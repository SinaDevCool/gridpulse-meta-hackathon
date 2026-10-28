from __future__ import annotations

from capacity_backtest.phase2.fatigue import FatigueLimits, evaluate_fatigue
from capacity_backtest.phase2.thermal_workload import (
    CoolingConfig,
    WorkloadConfig,
    simulate_cooling_workload,
)


def test_cooling_and_workload_rebound_are_stateful_and_recovered() -> None:
    result = simulate_cooling_workload(
        [4, 4, 0, 0], [0, 0, 6, 6],
        CoolingConfig(8, 3, 6, maximum_thermal_debt_mwh=6, recovery_power_mw=3),
        WorkloadConfig(3, 3, deadline_hours=4),
    )
    assert result.cooling_rebound_peak_mw == 3
    assert result.workload_rebound_peak_mw > 0
    assert result.ending_thermal_debt_mwh == 0
    assert result.ending_workload_backlog_mwh == 0
    assert result.deadline_violation_hours == 0


def test_workload_deadline_violation_remains_explicit() -> None:
    result = simulate_cooling_workload(
        [4, 0, 0], [0, 0, 0],
        CoolingConfig(8, 0, 0, maximum_thermal_debt_mwh=0),
        WorkloadConfig(4, 1, deadline_hours=1),
    )
    assert result.deadline_violation_hours > 0
    assert result.ending_workload_backlog_mwh == 4


def test_fatigue_detects_consecutive_daily_weekly_cooldown_and_energy_burden() -> None:
    result = evaluate_fatigue(
        [5, 5, 5, 0, 5, 5],
        battery_cycles=3,
        limits=FatigueLimits(2, 4, 1, 20, 2, 2),
    )
    assert not result.passed
    assert "maximum_consecutive_event_hours" in result.violations
    assert "minimum_cooldown_hours" in result.violations
    assert "annual_shifted_energy_mwh" in result.violations
    assert "annual_battery_cycles" in result.violations
