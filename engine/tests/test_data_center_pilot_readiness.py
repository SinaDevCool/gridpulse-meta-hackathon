from capacity_backtest.data_center.data_readiness import (
    DataReadinessState,
    DatasetReadiness,
    assess_pilot_data_readiness,
)


def test_synthetic_pilot_can_test_software_but_not_create_dependable_claim() -> None:
    datasets = tuple(
        DatasetReadiness(name, DataReadinessState.SYNTHETIC_SUBSTITUTE, "a" * 64)
        for name in ("pcc", "workload", "cooling")
    )
    result = assess_pilot_data_readiness(
        datasets, required_dataset_ids=("pcc", "workload", "cooling")
    )
    assert result.shadow_pilot_ready
    assert not result.dependable_claim_ready
