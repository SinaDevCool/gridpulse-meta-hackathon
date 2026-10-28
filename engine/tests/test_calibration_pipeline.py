import json
from datetime import datetime, timedelta, timezone

import pytest

from capacity_backtest.application.calibration import prepare_workload_calibration


def capture():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(6):
        a = start + timedelta(hours=i * 2)
        b = a + timedelta(hours=1)
        rows.append({"execution_id": f"e{i}", "workload_id": "w", "submitted_at": a.isoformat(), "started_at": a.isoformat(),
            "ended_at": b.isoformat(), "available_at": b.isoformat(), "gpu_model": "test", "gpu_count": 8,
            "power_cap_mw": .1 + (i % 2) * .1, "measured_power_mw": .1 + (i % 2) * .1, "completed_work_fraction": 1, "checkpoint_count": 0,
            "reference_work_duration_minutes": 60, "configuration_id": "fixed", "power_boundary": "gpu"})
    return rows


def metadata():
    return {"dataset_id": "d", "source": "operator-export", "license": "operator-permission", "evidence_cutoff": "2026-01-02T00:00:00Z",
        "train_end": "2026-01-01T04:00:00Z", "validation_end": "2026-01-01T08:00:00Z", "truth_class": "operator_confirmed", "workload_id": "w"}


def test_pipeline_keeps_test_data_out_of_fit_and_never_activates():
    result = prepare_workload_calibration(json.dumps(capture()).encode(), **metadata())
    assert result["ready_for_human_review"]
    assert not result["activated"]
    assert result["validation"]["training_executions"] == 2
    assert result["test"]["training_executions"] == 2
    assert set(result["dataset"]["train_ids"]).isdisjoint(result["dataset"]["test_ids"])


def test_pipeline_rejects_late_or_unproven_available_data():
    rows = capture()
    rows[-1]["available_at"] = "2026-01-03T00:00:00Z"
    with pytest.raises(ValueError, match="availability"):
        prepare_workload_calibration(json.dumps(rows).encode(), **metadata())
