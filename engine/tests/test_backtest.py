import json
from pathlib import Path

import pytest

from capacity_backtest.backtest import BenchmarkRecord, estimate, evaluate, load_study
from capacity_backtest.contracts import TruthClass

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def study_and_truth():
    study = load_study(ROOT / "config/studies/berlin_capacity_backtest.yaml")
    payload = json.loads((ROOT / "reports/backtest-results.json").read_text(encoding="utf-8"))
    return study, [BenchmarkRecord(**record) for record in payload["records"]]


def test_generated_full_benchmark_is_complete_and_explicitly_synthetic(study_and_truth):
    _study, truth = study_and_truth
    assert len(truth) == 8 * 10 * 4 * 2
    assert all(item.validation_class == TruthClass.SYNTHETIC_BENCHMARK for item in truth)
    assert all(item.truth_capacity_mw >= 0 for item in truth)
    assert all(item.full_contingency_case_count > item.graph_selected_case_count for item in truth)
    assert len({item.network_id for item in truth}) == 8
    assert len({item.node_id for item in truth}) >= 10


def test_estimator_is_leave_one_network_out_and_fails_release_closed(study_and_truth):
    study, truth = study_and_truth
    estimates = estimate(truth, study["capacity_bands_mw"])
    metrics = evaluate(truth, estimates, study)
    assert len(estimates) == len(truth)
    assert all(item.truth_class == "experimental_estimate" for item in estimates)
    assert all(
        actual.network_id == predicted.network_id for actual, predicted in zip(truth, estimates)
    )
    assert metrics["ranking_gate_passed"] is False
    assert metrics["capacity_gate_passed"] is False
    assert metrics["mean_contingency_reduction_ratio"] > 0.5
    assert metrics["network_family_count"] == 8
    assert 0 <= metrics["contingency_selector_recall"] <= 1


def test_no_estimate_claims_operator_confirmation(study_and_truth):
    study, truth = study_and_truth
    estimates = estimate(truth, study["capacity_bands_mw"])
    assert "operator_confirmed" not in repr(estimates)
