"""Facility power balance composed from canonical resource trajectories."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.phase2.battery import BatteryTrajectory
from capacity_backtest.phase2.phase_power import (
    PhasePowerAssessment,
    PhasePowerSpecification,
    validate_phase_power,
)

from .contracts import PlanningInterval, validate_intervals
from .portfolio import PortfolioTrajectory


@dataclass(frozen=True)
class FacilityConfig:
    facility_id: str
    site_id: str
    import_limit_mw: float
    cooling_baseline_mw: float
    cooling_load_factor: float
    networking_power_mw: float
    storage_power_mw: float
    fixed_auxiliary_power_mw: float
    ups_loss_fraction: float
    distribution_loss_fraction: float
    reactive_min_mvar: float
    reactive_max_mvar: float
    minimum_power_factor: float
    maximum_phase_unbalance_fraction: float
    pue_assumption: float
    heat_reuse_mw: float
    truth_class: TruthClass
    import_limit_profile_mw: tuple[float, ...] | None = None

    def import_limits(self, count: int) -> tuple[float, ...]:
        self.validate()
        if self.import_limit_profile_mw is not None:
            if len(self.import_limit_profile_mw) != count:
                raise ValueError("connection envelope must align with planning intervals")
            return self.import_limit_profile_mw
        return (self.import_limit_mw,) * count

    def validate(self) -> None:
        if not isfinite(self.import_limit_mw):
            raise ValueError("facility import limit must be finite")
        if self.import_limit_profile_mw is not None and (
            not self.import_limit_profile_mw
            or any(
                isinstance(value, bool)
                or not isfinite(value)
                or not 0 <= value <= self.import_limit_mw
                for value in self.import_limit_profile_mw
            )
        ):
            raise ValueError(
                "connection envelope must be finite, nonnegative and below the connection ceiling"
            )
        if not self.facility_id or not self.site_id or self.import_limit_mw <= 0:
            raise ValueError("facility identity and import limit are required")
        values = (
            self.cooling_baseline_mw,
            self.cooling_load_factor,
            self.networking_power_mw,
            self.storage_power_mw,
            self.fixed_auxiliary_power_mw,
            self.ups_loss_fraction,
            self.distribution_loss_fraction,
            self.maximum_phase_unbalance_fraction,
            self.heat_reuse_mw,
        )
        if min(values) < 0 or max(self.ups_loss_fraction, self.distribution_loss_fraction) >= 1:
            raise ValueError("facility loads and loss fractions are invalid")
        if self.pue_assumption < 1 or not 0 < self.minimum_power_factor <= 1:
            raise ValueError("facility PUE or power factor is invalid")
        if self.reactive_min_mvar > self.reactive_max_mvar:
            raise ValueError("facility reactive capability bounds are reversed")
        coerce_truth_class(self.truth_class)


@dataclass(frozen=True)
class FacilityPowerPoint:
    interval_index: int
    it_power_mw: float
    cooling_power_mw: float
    auxiliary_power_mw: float
    losses_mw: float
    battery_charge_mw: float
    battery_discharge_mw: float
    onsite_generation_mw: float
    grid_import_mw: float
    import_limit_violation_mw: float


@dataclass(frozen=True)
class FacilityPowerTrajectory:
    facility_id: str
    points: tuple[FacilityPowerPoint, ...]
    phase_power_assessments: tuple[PhasePowerAssessment, ...]
    maximum_grid_import_mw: float
    import_limit_violation_count: int


def build_facility_trajectory(
    config: FacilityConfig,
    intervals: tuple[PlanningInterval, ...],
    portfolio: PortfolioTrajectory,
    *,
    cooling_adjustment_mw: tuple[float, ...] | None = None,
    batteries: tuple[BatteryTrajectory, ...] = (),
    onsite_generation_mw: tuple[float, ...] | None = None,
) -> FacilityPowerTrajectory:
    config.validate()
    validate_intervals(intervals)
    if len(portfolio.power_points) != len(intervals):
        raise ValueError("portfolio and facility horizons must align")
    cooling_adjustment = cooling_adjustment_mw or (0.0,) * len(intervals)
    onsite = onsite_generation_mw or (0.0,) * len(intervals)
    if len(cooling_adjustment) != len(intervals) or len(onsite) != len(intervals):
        raise ValueError("facility component trajectories must align")
    if any(len(battery.points) != len(intervals) for battery in batteries):
        raise ValueError("battery and facility horizons must align")
    limits = config.import_limits(len(intervals))
    points, phase = [], []
    auxiliary = (
        config.networking_power_mw + config.storage_power_mw + config.fixed_auxiliary_power_mw
    )
    for interval in intervals:
        index = interval.index
        it_power = portfolio.power_points[index].scheduled_it_power_mw
        cooling = max(
            0.0,
            config.cooling_baseline_mw
            + config.cooling_load_factor * it_power
            + cooling_adjustment[index],
        )
        ups_losses = it_power * config.ups_loss_fraction
        distribution_losses = (it_power + cooling + auxiliary) * config.distribution_loss_fraction
        losses = ups_losses + distribution_losses
        battery_values = [battery.points[index].delivered_power_mw for battery in batteries]
        discharge = sum(max(0.0, value) for value in battery_values)
        charge = sum(max(0.0, -value) for value in battery_values)
        grid = max(
            0.0, it_power + cooling + auxiliary + losses + charge - discharge - onsite[index]
        )
        violation = max(0.0, grid - limits[index])
        points.append(
            FacilityPowerPoint(
                index,
                it_power,
                cooling,
                auxiliary,
                losses,
                charge,
                discharge,
                onsite[index],
                grid,
                violation,
            )
        )
        active = {name: grid / 3 for name in ("a", "b", "c")}
        reactive = {name: 0.0 for name in ("a", "b", "c")}
        phase.append(
            validate_phase_power(
                PhasePowerSpecification(
                    active,
                    reactive,
                    config.maximum_phase_unbalance_fraction,
                    config.minimum_power_factor,
                    config.reactive_min_mvar,
                    config.reactive_max_mvar,
                )
            )
        )
    return FacilityPowerTrajectory(
        config.facility_id,
        tuple(points),
        tuple(phase),
        max(item.grid_import_mw for item in points),
        sum(item.import_limit_violation_mw > 1e-9 for item in points),
    )
