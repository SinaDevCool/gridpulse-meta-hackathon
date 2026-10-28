import pytest

from capacity_backtest.optimized_deflex import optimize_flexibility
from grid_data.deflex import FlexibilityPolicy


def test_optimized_dispatch_respects_envelope_and_terminal_soc():
    policy = FlexibilityPolicy(
        interruptible_fraction=0.2,
        maximum_interruption_hours=4,
        annual_constrained_hour_budget=10,
        recovery_hours=4,
        battery_power_mw=2,
        battery_energy_mwh=4,
        charge_efficiency=0.9,
        discharge_efficiency=0.9,
        minimum_reserve_soc_fraction=0.1,
        ramp_limit_mw_per_hour=10,
        critical_load_fraction=0.8,
        workload_deadline_hours=6,
        battery_degradation_cost_per_mwh=1,
    )
    result = optimize_flexibility([10.0] * 24, [8.0] * 24, [8.0] * 24, policy)
    assert result["unsafe_overstatement_hours"] == 0
    assert result["ending_soc_mwh"] == pytest.approx(4.0)
    assert result["classification"] == "synthetic_benchmark"


def test_optimized_dispatch_rejects_misaligned_series():
    policy = FlexibilityPolicy(0.1, 2, 10, 2, 1, 2)
    with pytest.raises(ValueError, match="aligned"):
        optimize_flexibility([1.0], [1.0, 2.0], [1.0], policy)


def test_optimized_dispatch_supports_unbounded_ramp_policy():
    policy = FlexibilityPolicy(0.1, 2, 10, 2, 1, 2, ramp_limit_mw_per_hour=None)
    result = optimize_flexibility([2.0] * 6, [2.0] * 6, [2.0] * 6, policy)
    assert result["unsafe_overstatement_hours"] == 0
