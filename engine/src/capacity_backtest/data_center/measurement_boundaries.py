"""Physical measurement boundaries for auditable facility energy accounting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain.base import parse_aware_timestamp


class MeasuredComponent(str, Enum):
    PCC = "pcc"
    UPS_INPUT = "ups_input"
    UPS_OUTPUT = "ups_output"
    IT = "it"
    COOLING = "cooling"
    AUXILIARY = "auxiliary"
    BATTERY_AC = "battery_ac"
    ONSITE_GENERATION = "onsite_generation"
    BACKUP_GENERATION = "backup_generation"
    HEAT_REUSE = "heat_reuse"
    WATER = "water"


def validate_component_unit(component: MeasuredComponent, unit: str) -> None:
    """Keep physical units explicit; never silently mix power and energy."""
    component = MeasuredComponent(component)
    allowed = (
        {"m3", "m3/h", "L", "L/s"}
        if component == MeasuredComponent.WATER
        else {"W", "kW", "MW", "Wh", "kWh", "MWh"}
    )
    if unit not in allowed:
        raise ValueError("unit is incompatible with measured component")


@dataclass(frozen=True)
class MeteringPoint:
    measurement_id: str
    facility_id: str
    component: MeasuredComponent
    physical_location: str
    unit: str
    interval_seconds: int
    source_system: str
    meter_class: str | None
    upstream_boundary: str | None
    downstream_boundary: str | None
    calibration_at: str | None
    truth_class: TruthClass
    sample_kind: str = "instantaneous"
    sign_multiplier: int = 1
    uncertainty_fraction: float | None = None

    def validate(self) -> None:
        if (
            not all(
                (
                    self.measurement_id,
                    self.facility_id,
                    self.physical_location,
                    self.unit,
                    self.source_system,
                )
            )
            or self.interval_seconds <= 0
        ):
            raise ValueError("metering-point identity or resolution is invalid")
        validate_component_unit(self.component, self.unit)
        if self.sample_kind not in {"instantaneous", "interval_average", "cumulative_energy"}:
            raise ValueError("unsupported measurement sample kind")
        if self.sign_multiplier not in {-1, 1}:
            raise ValueError("sign multiplier must be -1 or 1")
        energy = self.unit in {"Wh", "kWh", "MWh"}
        if self.component != MeasuredComponent.WATER and (
            (self.sample_kind == "cumulative_energy") != energy
        ):
            raise ValueError("sample kind does not match measurement units")
        if self.uncertainty_fraction is not None and (
            not isfinite(self.uncertainty_fraction) or not 0 <= self.uncertainty_fraction < 1
        ):
            raise ValueError("measurement uncertainty must be a finite fraction")
        if self.calibration_at is not None:
            parse_aware_timestamp(self.calibration_at, "meter calibration_at")
        coerce_truth_class(self.truth_class)


@dataclass(frozen=True)
class FacilityEnergyBoundary:
    facility_id: str
    points: tuple[MeteringPoint, ...]
    unmetered_components: tuple[MeasuredComponent, ...] = ()
    schema_version: str = "gridpulse-facility-energy-boundary-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-facility-energy-boundary-v1" or not self.points:
            raise ValueError("facility energy boundary is invalid")
        identifiers = []
        components = []
        for point in self.points:
            point.validate()
            if point.facility_id != self.facility_id:
                raise ValueError("metering point belongs to a different facility")
            identifiers.append(point.measurement_id)
            components.append(point.component)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("metering-point identities must be unique")
        if MeasuredComponent.PCC not in components:
            raise ValueError("facility boundary requires a PCC measurement")
        if set(components) & set(self.unmetered_components):
            raise ValueError("a component cannot be metered and unmetered")


@dataclass(frozen=True)
class EnergyBalanceAssessment:
    supplied_mwh: float
    consumed_mwh: float
    residual_mwh: float
    residual_fraction: float
    passed: bool


def assess_energy_balance(
    *, supplied_mwh: float, consumed_mwh: float, tolerance_fraction: float = 0.01
) -> EnergyBalanceAssessment:
    if (
        not all(isfinite(value) for value in (supplied_mwh, consumed_mwh, tolerance_fraction))
        or min(supplied_mwh, consumed_mwh, tolerance_fraction) < 0
        or tolerance_fraction >= 1
    ):
        raise ValueError("energy-balance inputs are invalid")
    residual = supplied_mwh - consumed_mwh
    fraction = abs(residual) / supplied_mwh if supplied_mwh else float(consumed_mwh > 0)
    return EnergyBalanceAssessment(
        supplied_mwh, consumed_mwh, residual, fraction, fraction <= tolerance_fraction
    )
