"""Evidence-weighted delivery credibility and correlated non-delivery reserve."""

from __future__ import annotations

import math
from dataclasses import dataclass

from capacity_backtest.domain import FlexibilityPortfolio
from capacity_backtest.domain.base import parse_aware_timestamp


@dataclass(frozen=True)
class DeliveryEvidence:
    resource_id: str
    event_at: str
    requested_mw: float
    delivered_mw: float
    response_seconds: float
    verified: bool = True

    def validate(self) -> None:
        parse_aware_timestamp(self.event_at, "delivery event_at")
        if min(self.requested_mw, self.delivered_mw, self.response_seconds) < 0:
            raise ValueError("delivery evidence cannot be negative")
        if self.delivered_mw > self.requested_mw + 1e-9:
            raise ValueError("delivered power cannot exceed requested power")


@dataclass(frozen=True)
class ResourceCredibility:
    resource_id: str
    evidence_count: int
    weighted_delivery_probability: float
    conservative_delivery_probability: float
    delivered_ratio: float
    response_success_probability: float
    dependable_power_mw: float
    correlation_group: str


@dataclass(frozen=True)
class PortfolioCredibility:
    resources: tuple[ResourceCredibility, ...]
    declared_power_mw: float
    expected_delivered_power_mw: float
    dependable_power_mw: float
    non_delivery_reserve_mw: float
    confidence_level: float


def _wilson_lower(successes: float, trials: float, z: float) -> float:
    if trials <= 0:
        return 0.0
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = proportion + z * z / (2 * trials)
    spread = z * math.sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials))
    return max(0.0, (centre - spread) / denominator)


def assess_portfolio_credibility(
    portfolio: FlexibilityPortfolio,
    evidence: list[DeliveryEvidence],
    *,
    assessed_at: str,
    response_deadline_seconds: float,
    correlation_groups: dict[str, str] | None = None,
    confidence_level: float = 0.95,
    correlation: float = 0.25,
) -> PortfolioCredibility:
    portfolio.validate()
    now = parse_aware_timestamp(assessed_at, "assessed_at")
    if response_deadline_seconds < 0 or not 0 < confidence_level < 1 or not 0 <= correlation <= 1:
        raise ValueError("invalid credibility parameters")
    groups = correlation_groups or {}
    by_resource: dict[str, list[tuple[DeliveryEvidence, float]]] = {}
    known = {resource.resource_id for resource in portfolio.resources}
    for evidence_item in evidence:
        evidence_item.validate()
        if evidence_item.resource_id not in known or not evidence_item.verified:
            continue
        age_days = max(
            0.0,
            (
                now - parse_aware_timestamp(evidence_item.event_at, "event_at")
            ).total_seconds()
            / 86400,
        )
        weight = math.exp(-age_days / 180)
        by_resource.setdefault(evidence_item.resource_id, []).append((evidence_item, weight))
    z = 1.645 if confidence_level <= 0.95 else 2.326
    results = []
    for resource in portfolio.resources:
        rows = by_resource.get(resource.resource_id, [])
        total_weight = sum(weight for _, weight in rows)
        delivered_success = sum(weight * int(row.delivered_mw + 1e-9 >= row.requested_mw) for row, weight in rows)
        response_success = sum(weight * int(row.response_seconds <= response_deadline_seconds) for row, weight in rows)
        ratios = [row.delivered_mw / row.requested_mw for row, _ in rows if row.requested_mw > 0]
        ratio = sum(ratios) / len(ratios) if ratios else 0.0
        observed = delivered_success / total_weight if total_weight else 0.0
        conservative = _wilson_lower(delivered_success, total_weight, z)
        response_probability = response_success / total_weight if total_weight else 0.0
        combined = min(resource.availability_probability, conservative, response_probability) * ratio
        results.append(
            ResourceCredibility(
                resource.resource_id, len(rows), observed, conservative, ratio,
                response_probability, resource.power_mw * combined,
                groups.get(resource.resource_id, resource.resource_id),
            )
        )
    declared = sum(resource.power_mw for resource in portfolio.resources)
    expected = sum(
        resource.power_mw * credibility.weighted_delivery_probability * credibility.delivered_ratio
        for resource, credibility in zip(portfolio.resources, results)
    )
    dependable_mean = sum(item.dependable_power_mw for item in results)
    group_members: dict[str, list[float]] = {}
    for item in results:
        group_members.setdefault(item.correlation_group, []).append(item.dependable_power_mw)
    correlated_penalty = correlation * sum(
        sum(members) - max(members) for members in group_members.values() if members
    )
    dependable = max(0.0, dependable_mean - correlated_penalty)
    return PortfolioCredibility(
        tuple(results), declared, expected, dependable,
        max(0.0, declared - dependable), confidence_level,
    )
