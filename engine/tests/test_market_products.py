import pytest

from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.uncertainty import UncertainFlexibilityAssessment
from capacity_backtest.market.contracts import MarketDirection, MarketProduct, PaymentType
from capacity_backtest.market.eligibility import assess_market_eligibility
from capacity_backtest.market.settlement import settle_delivery
from capacity_backtest.phase1.risk import RiskPolicy

from .test_data_center_flexibility_assessment import requirement


def product(minimum_bid=0.01):
    return MarketProduct(
        "p", "synthetic", "DE", MarketDirection.REDUCE_IMPORT, minimum_bid, 15, 0,
        3600, 15, 60, 4, 0, 24, "metered_baseline", PaymentType.COMBINED,
        5, 100, 200, "2026-01-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00",
        TruthClass.SYNTHETIC_DEMONSTRATION,
    )


def uncertain():
    return UncertainFlexibilityAssessment(RiskPolicy.CHANCE_CONSTRAINED, 0.9, (), 1, 0, 0, 0.05, True, (), "a" * 64)


def test_market_eligibility_and_settlement_remain_nonclaims() -> None:
    eligible = assess_market_eligibility(product(), requirement(), uncertain())
    assert eligible.eligible and not eligible.capacity_claim
    settled = settle_delivery(product(), offered_mw=0.05, availability_hours=2, requested_mwh=0.1, verified_delivered_mwh=0.08)
    assert settled.delivered_mwh == 0.08
    assert settled.non_delivery_penalty_eur == pytest.approx(4)


def test_minimum_bid_is_fail_closed() -> None:
    assert "minimum_bid" in assess_market_eligibility(product(1), requirement(), uncertain()).blockers
