from datetime import datetime, timedelta, timezone

from capacity_backtest.queue_backtest import FEATURES, classification_metrics, run_queue_backtest


def rows(count: int = 320) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = []
    labels = ("approved_firm", "conditional_offer", "rejected_synthetic_constraint")
    for index in range(count):
        requested = (10, 25, 50, 100, 200)[index % 5]
        row = {
            "request_id": f"r-{index}",
            "submitted_at": (start + timedelta(days=index)).isoformat(),
            "network_id": f"family-{index % 8}",
            "node_id": f"node-{index % 15}",
            "requested_mw": requested,
            "requested_mva": requested / 0.96,
            "power_factor": 0.96,
            "target_lead_years": 2,
            "reserved_before_mw": index % 90,
            "prior_decided_requests": index // 80,
            "prior_requested_mw": float(index % 500),
            "prior_firm_approvals": index % 3,
            "prior_conditional_offers": index % 2,
            "prior_rejections": index % 4,
            "known_outage_count": index % 5,
            "month_sin": 0.0,
            "month_cos": 1.0,
            "label": labels[(index + requested // 25) % 3],
            "firm_mw_offered": 0.0,
            "conditional_mw_offered": 0.0,
            "evidence_cutoff": (start + timedelta(days=index)).isoformat(),
            "truth_class": "synthetic_benchmark",
            "capacity_claim": False,
        }
        assert all(name in row for name in FEATURES)
        result.append(row)
    return result


def test_queue_backtest_is_temporal_and_family_held_out() -> None:
    result = run_queue_backtest(rows())
    designs = {fold["design"] for fold in result["folds"]}
    assert designs == {"rolling_origin", "leave_one_network_family_out"}
    assert result["release_gate_passed"] is False
    assert result["capacity_claim"] is False


def test_unsafe_firm_prediction_is_measured() -> None:
    sample = rows(3)
    probability = [[0.9, 0.05, 0.05] for _ in sample]
    metrics = classification_metrics(sample, probability)
    assert metrics["unsafe_firm_prediction_rate"] > 0
