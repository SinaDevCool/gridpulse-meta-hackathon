"""Delivery-evidence orchestration into existing credibility and capacity owners."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.domain import FlexibilityPortfolio
from capacity_backtest.phase1.capacity import Phase1CapacityAssessment
from capacity_backtest.phase2.battery import BatteryTrajectory
from capacity_backtest.phase2.capacity import (
    DependableCapacityAssessment,
    build_dependable_capacity_assessment,
)
from capacity_backtest.phase2.credibility import PortfolioCredibility, assess_portfolio_credibility
from capacity_backtest.phase2.fatigue import FatigueAssessment
from capacity_backtest.phase2.phase_power import PhasePowerAssessment
from capacity_backtest.phase2.thermal_workload import ThermalWorkloadTrajectory
from capacity_backtest.phase3.delivery import DeliveryVerification


@dataclass(frozen=True)
class VerificationSummary:
    event_count: int
    verified_event_count: int
    passed_event_count: int
    baseline_quality_score: float
    credibility: PortfolioCredibility
    dependable_capacity: DependableCapacityAssessment | None
    blockers: tuple[str, ...]
    capacity_claim: bool = False
    schema_version: str = "gridpulse-delivery-verification-summary-v1"


def assess_baseline_quality(
    baseline_mw: tuple[float | None, ...], observed_mw: tuple[float | None, ...]
) -> float:
    if not baseline_mw or len(baseline_mw) != len(observed_mw):
        raise ValueError("baseline-quality series must be non-empty and aligned")
    valid = [(base, actual) for base, actual in zip(baseline_mw, observed_mw) if base is not None and actual is not None]
    if not valid:
        return 0.0
    missing_fraction = 1 - len(valid) / len(baseline_mw)
    scale = max(max(abs(float(base)), abs(float(actual))) for base, actual in valid)
    error = sum(abs(float(base) - float(actual)) for base, actual in valid) / len(valid)
    normalized_error = error / scale if scale else 0.0
    return max(0.0, min(1.0, 1 - missing_fraction - normalized_error))


def build_verification_summary(
    portfolio: FlexibilityPortfolio,
    deliveries: tuple[DeliveryVerification, ...],
    *,
    assessed_at: str,
    response_deadline_seconds: float,
    baseline_quality_score: float,
    minimum_events: int = 5,
    phase1: Phase1CapacityAssessment | None = None,
    fatigue: FatigueAssessment | None = None,
    phase_power: PhasePowerAssessment | None = None,
    batteries: list[BatteryTrajectory] | None = None,
    thermal_workload: ThermalWorkloadTrajectory | None = None,
) -> VerificationSummary:
    if not 0 <= baseline_quality_score <= 1 or minimum_events < 1:
        raise ValueError("verification quality threshold inputs are invalid")
    evidence = [item.evidence for item in deliveries]
    credibility = assess_portfolio_credibility(
        portfolio, evidence, assessed_at=assessed_at,
        response_deadline_seconds=response_deadline_seconds,
    )
    blockers = []
    verified_count = sum(item.evidence.verified for item in deliveries)
    if verified_count < minimum_events:
        blockers.append("insufficient_verified_events")
    if baseline_quality_score < 0.8:
        blockers.append("baseline_quality")
    dependable = None
    supplied = (phase1, fatigue, phase_power, thermal_workload)
    if any(item is not None for item in supplied):
        if not all(item is not None for item in supplied):
            raise ValueError("dependable-capacity inputs must be supplied together")
        assert phase1 is not None and fatigue is not None
        assert phase_power is not None and thermal_workload is not None
        dependable = build_dependable_capacity_assessment(
            phase1, credibility, fatigue, phase_power, batteries or [], thermal_workload
        )
        blockers.extend(dependable.blockers)
    return VerificationSummary(
        len(deliveries), verified_count, sum(item.passed for item in deliveries),
        baseline_quality_score, credibility, dependable, tuple(dict.fromkeys(blockers)),
    )
