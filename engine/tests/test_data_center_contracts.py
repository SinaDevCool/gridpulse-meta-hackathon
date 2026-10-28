import pytest

from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.contracts import AIWorkload, WorkloadKind, WorkloadSLA


def workload(**changes):
    values = {
        "workload_id": "job-1", "tenant_id": "tenant",
        "workload_kind": WorkloadKind.TRAINING,
        "earliest_start": "2026-01-01T00:00:00+00:00", "nominal_gpu_count": 8,
        "minimum_gpu_count": 4, "maximum_gpu_count": 16, "nominal_power_mw": 0.08,
        "minimum_power_cap_mw": 0.04, "expected_duration_minutes": 60,
        "checkpoint_duration_minutes": 15, "restart_duration_minutes": 15,
        "geographic_movement_permitted": False, "allowed_site_ids": ("site-a",),
        "data_residency_regions": ("DE",),
        "sla": WorkloadSLA("2026-01-01T04:00:00+00:00", 0.5, 0.5, 2, None, 1000),
        "truth_class": TruthClass.SYNTHETIC_DEMONSTRATION,
        "evidence_cutoff": "2025-12-31T00:00:00+00:00",
    }
    values.update(changes)
    return AIWorkload(**values)


def test_workload_contract_accepts_bounded_training_job() -> None:
    workload().validate()


def test_invalid_gpu_power_and_movement_bounds_fail_closed() -> None:
    with pytest.raises(ValueError, match="GPU bounds"):
        workload(minimum_gpu_count=9).validate()
    with pytest.raises(ValueError, match="power bounds"):
        workload(minimum_power_cap_mw=0.09).validate()
    with pytest.raises(ValueError, match="at least two"):
        workload(geographic_movement_permitted=True).validate()


def test_critical_inference_must_be_fully_protected() -> None:
    with pytest.raises(ValueError, match="fully protected"):
        workload(workload_kind=WorkloadKind.CRITICAL_INFERENCE).validate()
    critical = workload(
        workload_kind=WorkloadKind.CRITICAL_INFERENCE,
        minimum_gpu_count=8,
        sla=WorkloadSLA("2026-01-01T04:00:00+00:00", 0, 1, 0, 100, 1000),
    )
    critical.validate()
