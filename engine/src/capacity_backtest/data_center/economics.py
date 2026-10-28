"""Financial accounting over verified facility trajectories and delivery outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .contracts import PlanningInterval, validate_intervals
from .facility import FacilityPowerTrajectory
from .portfolio import PortfolioTrajectory


@dataclass(frozen=True)
class EconomicTariff:
    energy_price_eur_per_mwh: tuple[float, ...]
    demand_charge_eur_per_mw: float
    battery_wear_eur_per_mwh: float
    market_payment_eur_per_mwh: float
    non_delivery_penalty_eur_per_mwh: float

    def validate(self, size: int) -> None:
        if len(self.energy_price_eur_per_mwh) != size:
            raise ValueError("tariff prices must align with the horizon")
        non_energy = (
            self.demand_charge_eur_per_mw,
            self.battery_wear_eur_per_mwh,
            self.market_payment_eur_per_mwh,
            self.non_delivery_penalty_eur_per_mwh,
        )
        if not all(isfinite(value) for value in (*self.energy_price_eur_per_mwh, *non_energy)):
            raise ValueError("tariff values must be finite")
        if min(non_energy) < 0:
            raise ValueError("non-energy tariff values cannot be negative")


@dataclass(frozen=True)
class EconomicOutcome:
    energy_cost_eur: float
    demand_charge_eur: float
    sla_cost_eur: float
    battery_wear_eur: float
    market_revenue_eur: float
    non_delivery_penalty_eur: float
    avoided_peak_charge_eur: float
    net_cost_eur: float


def integrate_energy_cost(
    intervals: tuple[PlanningInterval, ...], import_mw: tuple[float, ...], prices: tuple[float, ...]
) -> float:
    """Interval-weighted EUR accounting shared by replay and fixed-plan tools."""
    validate_intervals(intervals)
    if len(import_mw) != len(intervals) or len(prices) != len(intervals):
        raise ValueError("energy accounting horizons must align")
    if not all(isfinite(value) for value in (*import_mw, *prices)) or min(import_mw) < 0:
        raise ValueError("energy accounting requires finite import and prices")
    return sum(
        power * price * interval.duration_minutes / 60
        for power, price, interval in zip(import_mw, prices, intervals)
    )


def calculate_economics(
    intervals: tuple[PlanningInterval, ...],
    baseline: FacilityPowerTrajectory,
    actual: FacilityPowerTrajectory,
    portfolio: PortfolioTrajectory,
    tariff: EconomicTariff,
    *,
    requested_reduction_mw: tuple[float, ...],
    delivered_reduction_mw: tuple[float, ...],
    battery_throughput_mwh: float = 0.0,
) -> EconomicOutcome:
    validate_intervals(intervals)
    size = len(intervals)
    tariff.validate(size)
    if any(len(values) != size for values in (requested_reduction_mw, delivered_reduction_mw)):
        raise ValueError("delivery and tariff horizons must align")
    if len(baseline.points) != size or len(actual.points) != size or battery_throughput_mwh < 0:
        raise ValueError("economic inputs are invalid or misaligned")
    if not all(
        isfinite(value)
        for value in (
            *requested_reduction_mw,
            *delivered_reduction_mw,
            battery_throughput_mwh,
            *(point.grid_import_mw for point in actual.points),
        )
    ):
        raise ValueError("economic trajectories must be finite")
    energy = integrate_energy_cost(
        intervals,
        tuple(point.grid_import_mw for point in actual.points),
        tariff.energy_price_eur_per_mwh,
    )
    demand = actual.maximum_grid_import_mw * tariff.demand_charge_eur_per_mw
    avoided = (
        max(0.0, baseline.maximum_grid_import_mw - actual.maximum_grid_import_mw)
        * tariff.demand_charge_eur_per_mw
    )
    delivered_energy = sum(
        value * interval.duration_minutes / 60
        for value, interval in zip(delivered_reduction_mw, intervals)
    )
    shortfall_energy = sum(
        max(0.0, requested - delivered) * interval.duration_minutes / 60
        for requested, delivered, interval in zip(
            requested_reduction_mw, delivered_reduction_mw, intervals
        )
    )
    revenue = delivered_energy * tariff.market_payment_eur_per_mwh
    penalty = shortfall_energy * tariff.non_delivery_penalty_eur_per_mwh
    wear = battery_throughput_mwh * tariff.battery_wear_eur_per_mwh
    net = energy + demand + portfolio.total_sla_penalty_eur + wear + penalty - revenue
    return EconomicOutcome(
        energy, demand, portfolio.total_sla_penalty_eur, wear, revenue, penalty, avoided, net
    )
