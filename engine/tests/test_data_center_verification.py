from capacity_backtest.data_center.verification import (
    assess_baseline_quality,
    build_verification_summary,
)

from .test_phase0_domain import portfolio
from .test_phase3_delivery_simulation import successful_verification


def test_verification_reuses_credibility_and_requires_sample_depth() -> None:
    deliveries = tuple(successful_verification() for _ in range(5))
    result = build_verification_summary(
        portfolio(), deliveries, assessed_at="2026-02-01T00:00:00+00:00",
        response_deadline_seconds=10, baseline_quality_score=0.9,
    )
    assert result.verified_event_count == 5
    assert result.credibility.dependable_power_mw > 0
    assert not result.blockers and not result.capacity_claim


def test_verification_fails_closed_on_weak_baseline_and_sample() -> None:
    result = build_verification_summary(
        portfolio(), (successful_verification(),), assessed_at="2026-02-01T00:00:00+00:00",
        response_deadline_seconds=10, baseline_quality_score=0.5,
    )
    assert set(result.blockers) == {"insufficient_verified_events", "baseline_quality"}


def test_baseline_quality_accounts_for_error_and_missingness() -> None:
    assert assess_baseline_quality((10, 10), (10, 10)) == 1
    assert assess_baseline_quality((10, None), (8, 10)) < 0.5
