from __future__ import annotations

from datetime import datetime, timedelta, timezone

from capacity_backtest.phase2.credibility import DeliveryEvidence, assess_portfolio_credibility

from .test_phase0_domain import portfolio


def evidence(resource_id: str, delivered: float, response: float, count: int = 20):
    now = datetime(2026, 1, 31, tzinfo=timezone.utc)
    return [
        DeliveryEvidence(
            resource_id, (now - timedelta(days=index)).isoformat(), 5, delivered, response
        )
        for index in range(count)
    ]


def test_credibility_derates_declared_power_and_creates_non_delivery_reserve() -> None:
    rows = evidence("battery-1", 5, 5) + evidence("workload-1", 4, 5)
    result = assess_portfolio_credibility(
        portfolio(), rows, assessed_at="2026-02-01T00:00:00+00:00",
        response_deadline_seconds=10, correlation_groups={"battery-1": "site", "workload-1": "site"},
    )
    assert 0 < result.dependable_power_mw < result.declared_power_mw
    assert result.non_delivery_reserve_mw == result.declared_power_mw - result.dependable_power_mw
    assert len(result.resources) == 2


def test_missing_or_slow_evidence_fails_closed_to_zero_dependability() -> None:
    result = assess_portfolio_credibility(
        portfolio(), evidence("battery-1", 5, 100),
        assessed_at="2026-02-01T00:00:00+00:00", response_deadline_seconds=10,
    )
    assert result.dependable_power_mw == 0
    workload = next(item for item in result.resources if item.resource_id == "workload-1")
    assert workload.evidence_count == 0


def test_shared_failure_group_increases_non_delivery_reserve() -> None:
    rows = evidence("battery-1", 5, 5) + evidence("workload-1", 5, 5)
    independent = assess_portfolio_credibility(
        portfolio(), rows, assessed_at="2026-02-01T00:00:00+00:00",
        response_deadline_seconds=10, correlation=0.5,
    )
    shared = assess_portfolio_credibility(
        portfolio(), rows, assessed_at="2026-02-01T00:00:00+00:00",
        response_deadline_seconds=10, correlation=0.5,
        correlation_groups={"battery-1": "site", "workload-1": "site"},
    )
    assert shared.dependable_power_mw < independent.dependable_power_mw
    assert shared.non_delivery_reserve_mw > independent.non_delivery_reserve_mw
