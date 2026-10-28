"""Technical eligibility mapping without capacity or delivery recalculation."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.data_center.uncertainty import UncertainFlexibilityAssessment
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement

from .contracts import MarketProduct


@dataclass(frozen=True)
class MarketEligibility:
    product_id: str
    eligible: bool
    offered_power_mw: float
    blockers: tuple[str, ...]
    capacity_claim: bool = False


def assess_market_eligibility(
    product: MarketProduct,
    requirement: FlexibilityRequirement,
    uncertainty: UncertainFlexibilityAssessment,
) -> MarketEligibility:
    product.validate()
    requirement.validate()
    blockers = list(requirement.blockers)
    offered = uncertainty.dependable_reduction_mw
    if not uncertainty.accepted:
        blockers.append("uncertainty_gate")
    if offered + 1e-9 < product.minimum_bid_mw:
        blockers.append("minimum_bid")
    if requirement.response_time_seconds is None:
        blockers.append("response_time_unknown")
    elif requirement.response_time_seconds > product.response_seconds:
        blockers.append("response_time")
    if requirement.minimum_notice_minutes is None:
        blockers.append("notice_time_unknown")
    elif requirement.minimum_notice_minutes > product.notice_minutes:
        blockers.append("notice_time")
    if requirement.maximum_event_duration_minutes is None:
        blockers.append("event_duration_unknown")
    elif requirement.maximum_event_duration_minutes < product.maximum_duration_minutes:
        blockers.append("event_duration")
    unique = tuple(dict.fromkeys(blockers))
    return MarketEligibility(product.product_id, not unique, offered, unique)
