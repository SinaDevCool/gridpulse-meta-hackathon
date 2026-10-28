"""Chronological, cutoff-safe replay of frozen facility plans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from capacity_backtest.domain.base import parse_aware_timestamp

from .contracts import PlanningInterval, validate_intervals
from .economics import EconomicOutcome, EconomicTariff, calculate_economics
from .facility import FacilityPowerTrajectory
from .portfolio import PortfolioTrajectory


@dataclass(frozen=True)
class HistoricalObservation:
    interval_index: int
    observed_at: str
    available_at: str
    grid_import_mw: float

    def validate(self) -> None:
        observed = parse_aware_timestamp(self.observed_at, "observed_at")
        available = parse_aware_timestamp(self.available_at, "available_at")
        if self.interval_index < 0 or self.grid_import_mw < 0 or available < observed:
            raise ValueError("historical observation is invalid")


@dataclass(frozen=True)
class HistoricalBacktestResult:
    planning_cutoff: str
    delivered_reduction_mw: tuple[float, ...]
    shortfall_mwh: float
    delivery_accuracy: float
    economics: EconomicOutcome
    fingerprint: str
    capacity_claim: bool = False
    automatic_live_dispatch_authorized: bool = False
    schema_version: str = "gridpulse-facility-historical-backtest-v1"


def run_historical_backtest(
    planning_cutoff: str,
    intervals: tuple[PlanningInterval, ...],
    baseline: FacilityPowerTrajectory,
    planned: FacilityPowerTrajectory,
    portfolio: PortfolioTrajectory,
    observations: tuple[HistoricalObservation, ...],
    tariff: EconomicTariff,
    *,
    event_intervals: tuple[bool, ...],
    required_reduction_mw: float,
    battery_throughput_mwh: float = 0.0,
) -> HistoricalBacktestResult:
    cutoff = parse_aware_timestamp(planning_cutoff, "planning_cutoff")
    validate_intervals(intervals)
    size = len(intervals)
    if len(observations) != size or len(event_intervals) != size:
        raise ValueError("backtest inputs must align with the planning horizon")
    if [item.interval_index for item in observations] != list(range(size)):
        raise ValueError("historical observations must be chronological")
    for observation in observations:
        observation.validate()
        if parse_aware_timestamp(observation.available_at, "available_at") <= cutoff:
            raise ValueError("historical replay observation leaked across planning cutoff")
    delivered = tuple(
        max(0.0, base.grid_import_mw - observation.grid_import_mw) if active else 0.0
        for base, observation, active in zip(baseline.points, observations, event_intervals)
    )
    requested = tuple(required_reduction_mw if active else 0.0 for active in event_intervals)
    dt = intervals[0].duration_minutes / 60
    shortfall = sum(max(0.0, request - actual) for request, actual in zip(requested, delivered)) * dt
    requested_energy = sum(requested) * dt
    accuracy = max(0.0, 1 - shortfall / requested_energy) if requested_energy else 1.0
    # The planned canonical trajectory is used for tariff accounting; observations are
    # delivery evidence and cannot silently replace unobserved facility components.
    economics = calculate_economics(
        intervals, baseline, planned, portfolio, tariff,
        requested_reduction_mw=requested, delivered_reduction_mw=delivered,
        battery_throughput_mwh=battery_throughput_mwh,
    )
    payload = {
        "cutoff": planning_cutoff, "observations": [asdict(item) for item in observations],
        "planned_facility": planned.facility_id,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return HistoricalBacktestResult(
        planning_cutoff, delivered, shortfall, accuracy, economics, fingerprint
    )
