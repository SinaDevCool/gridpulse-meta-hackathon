import pytest

from capacity_backtest.data_center.calibration_registry import (
    CalibrationCandidate,
    CalibrationRegistry,
)
from capacity_backtest.data_center.delivery_assessment import (
    BaselineMethod,
    DeliveryBaseline,
    verify_complete_delivery,
)


def test_complete_delivery_requires_recovery_and_precommitted_baseline() -> None:
    baseline = DeliveryBaseline(BaselineMethod.FROZEN_PLANNER, "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00", (10, 10), 0.1, "a" * 64)
    result = verify_complete_delivery(
        baseline, (9, 10), event_intervals=(True, False), requested_reduction_mw=1,
        response_met=True, rebound_mw=0, rebound_limit_mw=1, battery_recovered=True,
        thermal_recovered=True, workload_recovered=True, sla_met=True, telemetry_valid=True,
    )
    assert result.classification == "passed" and result.verified


def test_calibration_requires_review_holdout_improvement_and_supports_rollback() -> None:
    candidate = CalibrationCandidate("c", "facility", "v1", "v2", "2026-01-01T00:00:00+00:00", "a" * 64, "b" * 64, 0.2, 0.1)
    registry = CalibrationRegistry()
    registry.decide(candidate, reviewer_id="reviewer", decided_at="2026-01-02T00:00:00+00:00", approved=True, reason="held-out improvement")
    assert registry.active_version("facility") == "v2"
    assert registry.rollback("c") == "v1"
    worse = CalibrationCandidate("bad", "facility", "v1", "v3", "2026-01-01T00:00:00+00:00", "a" * 64, "b" * 64, 0.1, 0.2)
    with pytest.raises(ValueError, match="held-out improvement"):
        registry.decide(worse, reviewer_id="reviewer", decided_at="2026-01-02T00:00:00+00:00", approved=True, reason="bad")


def test_calibration_journal_survives_restart_and_rejects_stale_rollback(tmp_path):
    path = tmp_path / "decisions.jsonl"
    candidate = CalibrationCandidate("c", "facility", "v1", "v2", "2026-01-01T00:00:00Z", "a" * 64, "b" * 64, .2, .1)
    registry = CalibrationRegistry(journal_path=path)
    registry.decide(candidate, reviewer_id="reviewer", decided_at="2026-01-02T00:00:00Z", approved=True, reason="qualified")
    restored = CalibrationRegistry(journal_path=path)
    assert restored.active_version("facility") == "v2"
    restored.rollback("c")
    assert CalibrationRegistry(journal_path=path).active_version("facility") == "v1"
    with pytest.raises(ValueError, match="active"):
        restored.rollback("c")
