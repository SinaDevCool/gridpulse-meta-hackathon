import pytest

from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.power_profiles import (
    PiecewiseLinearPowerProfile,
    PowerThroughputPoint,
)


def profile():
    return PiecewiseLinearPowerProfile(
        "profile", "job-1",
        (PowerThroughputPoint(8, 0.04, 0.5), PowerThroughputPoint(8, 0.08, 1.0)),
        TruthClass.SYNTHETIC_DEMONSTRATION,
    )


def test_exact_and_interpolated_power_performance_is_deterministic() -> None:
    assert profile().evaluate(8, 0.04).throughput_fraction == 0.5
    first = profile().evaluate(8, 0.06)
    second = profile().evaluate(8, 0.06)
    assert first == second
    assert first.throughput_fraction == pytest.approx(0.75)


def test_profile_rejects_extrapolation_and_unknown_gpu_curve() -> None:
    with pytest.raises(ValueError, match="extrapolation"):
        profile().evaluate(8, 0.03)
    with pytest.raises(ValueError, match="no empirical curve"):
        profile().evaluate(4, 0.04)
