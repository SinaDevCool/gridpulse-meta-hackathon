import json

import pytest

from capacity_backtest.adapters.workload import parse_workload_executions
from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.profile_calibration import calibrate_power_profile


def rows():
    values = []
    for index, (power, work) in enumerate(((0.04, 0.5), (0.08, 1.0), (0.04, 0.5), (0.08, 1.0))):
        values.append({
            "execution_id": f"e{index}", "workload_id": "job", "submitted_at": "2026-01-01T00:00:00+00:00",
            "started_at": f"2026-01-01T0{index}:00:00+00:00", "ended_at": f"2026-01-01T0{index}:30:00+00:00",
            "gpu_model": "synthetic", "gpu_count": 8, "power_cap_mw": power,
            "measured_power_mw": power, "completed_work_fraction": work, "checkpoint_count": 0,
        })
    return values


def test_workload_adapter_and_heldout_profile_calibration() -> None:
    executions = parse_workload_executions(json.dumps(rows()).encode(), source_id="scheduler")
    result = calibrate_power_profile(
        "job", executions, holdout_execution_ids=("e2", "e3"),
        truth_class=TruthClass.SYNTHETIC_DEMONSTRATION,
    )
    assert result.accepted and result.holdout_executions == 2
    assert result.measured_power_curve
    assert all(len(point) == 3 for point in result.measured_power_curve)
    assert result.profile.evaluate(8, 0.04).throughput_fraction == 0.5


def test_heldout_power_and_throughput_errors_are_not_circular():
    data = rows()
    data[2]["measured_power_mw"] *= 0.5
    data[3]["completed_work_fraction"] *= 0.5
    executions = parse_workload_executions(json.dumps(data).encode(), source_id="scheduler")
    result = calibrate_power_profile("job", executions, holdout_execution_ids=("e2", "e3"),
                                    truth_class=TruthClass.SYNTHETIC_DEMONSTRATION)
    assert not result.accepted
    assert result.p90_power_error_fraction > 0.1
    assert result.p90_throughput_error_fraction > 0.1


def test_explicit_work_reference_normalizes_runtime_and_rejects_mixed_configuration():
    data = rows()
    for row in data:
        row.update(reference_work_duration_minutes=30, configuration_id="model-batch-v1")
    executions = parse_workload_executions(json.dumps(data).encode(), source_id="scheduler")
    assert executions[0].throughput_fraction() == 0.5
    data[-1]["configuration_id"] = "different-batch"
    mixed = parse_workload_executions(json.dumps(data).encode(), source_id="scheduler")
    with pytest.raises(ValueError, match="configurations"):
        calibrate_power_profile("job", mixed, holdout_execution_ids=("e2", "e3"), truth_class=TruthClass.SYNTHETIC_DEMONSTRATION)


@pytest.mark.parametrize("field,value", [("measured_power_mw", float("nan")), ("gpu_count", 0), ("checkpoint_count", 0.5)])
def test_execution_adapter_rejects_invalid_physical_values(field, value):
    data = rows()
    data[0][field] = value
    with pytest.raises((ValueError, TypeError)):
        parse_workload_executions(json.dumps(data).encode(), source_id="scheduler")


def test_real_data_cannot_qualify_with_legacy_work_reference():
    executions = parse_workload_executions(json.dumps(rows()).encode(), source_id="scheduler")
    result = calibrate_power_profile("job", executions, holdout_execution_ids=("e2", "e3"), truth_class=TruthClass.OPERATOR_CONFIRMED)
    assert not result.accepted
    assert "missing_work_reference_or_configuration" in result.blockers
