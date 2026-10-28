import pytest

from capacity_backtest.data_center.calibration import (
    calibrate_cooling,
    validate_battery_calibration,
    validate_facility_calibration,
)
from capacity_backtest.data_center.facility import build_facility_trajectory
from capacity_backtest.data_center.portfolio import WorkloadPortfolio, evaluate_portfolio
from capacity_backtest.phase2.battery import BatteryConfig, BatteryRequest, simulate_battery

from .test_data_center_contracts import workload
from .test_data_center_facility import config
from .test_data_center_power_profiles import profile
from .test_data_center_workloads import INTERVALS


def test_cooling_battery_and_facility_heldout_gates() -> None:
    cooling = calibrate_cooling((1, 2, 3), (10, 20, 30), (1.2, 2.4, 3.6), (4, 5), (40, 50), (4.8, 6.0))
    assert not cooling.metrics.accepted
    assert "unidentifiable_cooling_coefficients" in cooling.metrics.blockers
    assert "holdout_outside_training_range" in cooling.metrics.blockers
    requests = [BatteryRequest(interval.start, 0.01) for interval in INTERVALS]
    battery = simulate_battery(BatteryConfig("b", 0.1, 1, 1, 0, 0.9), requests)
    battery_metrics = validate_battery_calibration(
        battery, tuple(point.soc_mwh for point in battery.points),
        tuple(point.delivered_power_mw for point in battery.points),
    )
    assert battery_metrics.accepted
    job = workload()
    portfolio = evaluate_portfolio(WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS, (), site_id="site-a")
    facility = build_facility_trajectory(config(), INTERVALS, portfolio)
    metrics = validate_facility_calibration(facility, tuple(point.grid_import_mw for point in facility.points))
    assert metrics.accepted and metrics.p90_absolute_percentage_error == pytest.approx(0)


def test_cooling_artifact_reproduces_heldout_predictor():
    result = calibrate_cooling((1, 2, 3, 4), (10, 12, 11, 15), (2.5, 3.6, 4.55, 5.75),
                               (3,), (12,), (4.6,))
    assert result.cooling_load_factor > 0
    assert result.metrics.accepted
    assert result.predict(3, 12) == pytest.approx(4.6)
    with pytest.raises(ValueError, match="operating range"):
        result.predict(5, 16)


def test_calibration_rejects_nonfinite_and_gates_battery_boundaries_separately():
    with pytest.raises(ValueError, match="finite"):
        calibrate_cooling((1, 2), (10, 20), (1, 2), (3,), (30,), (float("nan"),))
    battery = simulate_battery(BatteryConfig("b", 0.1, 1, 1, 0, 0.9),
        [BatteryRequest(i.start, 0.01) for i in INTERVALS])
    result = validate_battery_calibration(battery, tuple(p.soc_mwh for p in battery.points),
        tuple(p.delivered_power_mw * 2 for p in battery.points))
    assert not result.accepted
    assert result.component_metrics[0].accepted
    assert not result.component_metrics[1].accepted
    assert result.maximum_absolute_error is None  # no mixed-unit aggregate
