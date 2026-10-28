"""Cooling thermal state and deadline-aware workload recovery."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite


@dataclass(frozen=True)
class CoolingConfig:
    baseline_power_mw: float
    maximum_reduction_mw: float
    thermal_capacity_mwh: float
    initial_thermal_debt_mwh: float = 0.0
    maximum_thermal_debt_mwh: float = 0.0
    recovery_power_mw: float = 0.0
    recovery_efficiency: float = 1.0

    def validate(self) -> None:
        if not all(isfinite(value) for value in vars(self).values()):
            raise ValueError("cooling parameters must be finite")
        if min(
            self.baseline_power_mw, self.maximum_reduction_mw, self.thermal_capacity_mwh,
            self.initial_thermal_debt_mwh, self.maximum_thermal_debt_mwh,
            self.recovery_power_mw,
        ) < 0:
            raise ValueError("cooling parameters cannot be negative")
        if self.maximum_thermal_debt_mwh > self.thermal_capacity_mwh:
            raise ValueError("maximum thermal debt exceeds thermal capacity")
        if self.initial_thermal_debt_mwh > self.maximum_thermal_debt_mwh:
            raise ValueError("initial thermal debt exceeds its limit")
        if not 0 < self.recovery_efficiency <= 1:
            raise ValueError("cooling recovery efficiency must be in (0, 1]")


@dataclass(frozen=True)
class ThermalEnvelope:
    """Optional single-zone replay parameters, requiring separate site calibration.

    This is not a rack/coolant model and does not replace the MILP debt model.
    Thermal capacity uses MWh thermal/K; conductance uses MW thermal/K.
    """
    capacity_mwh_per_k: float
    conductance_mw_per_k: float
    cooling_cop: float
    minimum_temperature_c: float
    maximum_temperature_c: float
    topology: str

    def validate(self) -> None:
        if not all(isfinite(value) for value in (self.capacity_mwh_per_k, self.conductance_mw_per_k,
            self.cooling_cop, self.minimum_temperature_c, self.maximum_temperature_c)):
            raise ValueError("thermal parameters must be finite")
        if self.capacity_mwh_per_k <= 0 or self.conductance_mw_per_k < 0 or self.cooling_cop <= 0:
            raise ValueError("thermal capacity/COP must be positive and conductance nonnegative")
        if self.minimum_temperature_c >= self.maximum_temperature_c or self.topology not in {"air", "direct_to_chip", "immersion", "hybrid"}:
            raise ValueError("thermal temperature bounds or topology are invalid")


def replay_temperature_envelope(config: ThermalEnvelope, *, initial_temperature_c: float,
    it_heat_mw: tuple[float, ...], cooling_electric_mw: tuple[float, ...],
    ambient_temperature_c: tuple[float, ...], interval_minutes: int) -> tuple[tuple[float, ...], tuple[int, ...]]:
    """Exact constant-input RC replay; returns N+1 boundary states and violations.

    Carry the final state into repeated events. No invented COP, thermal capacity
    or safety band is supplied. Positive cooling power removes COP * power heat.
    """
    config.validate()
    count = len(it_heat_mw)
    if not 1 <= count <= 96 or len(cooling_electric_mw) != count or len(ambient_temperature_c) != count or interval_minutes not in {15, 30, 60}:
        raise ValueError("thermal inputs must align within the replay budget")
    if not all(isfinite(value) for value in (initial_temperature_c, *it_heat_mw, *cooling_electric_mw, *ambient_temperature_c)) or min(*it_heat_mw, *cooling_electric_mw) < 0:
        raise ValueError("thermal replay requires finite inputs and nonnegative heat/power")
    states = [initial_temperature_c]
    dt = interval_minutes / 60
    for heat, cooling, ambient in zip(it_heat_mw, cooling_electric_mw, ambient_temperature_c):
        net_heat = heat - config.cooling_cop * cooling
        if config.conductance_mw_per_k == 0:
            temperature = states[-1] + net_heat * dt / config.capacity_mwh_per_k
        else:
            equilibrium = ambient + net_heat / config.conductance_mw_per_k
            temperature = equilibrium + (states[-1] - equilibrium) * exp(-config.conductance_mw_per_k * dt / config.capacity_mwh_per_k)
        if not isfinite(temperature):
            raise ValueError("thermal replay overflow")
        states.append(temperature)
    violations = tuple(index for index, value in enumerate(states) if not config.minimum_temperature_c <= value <= config.maximum_temperature_c)
    return tuple(states), violations


@dataclass(frozen=True)
class WorkloadConfig:
    maximum_shift_mw: float
    recovery_power_mw: float
    deadline_hours: int
    critical_fraction: float = 0.8

    def validate(self) -> None:
        if min(self.maximum_shift_mw, self.recovery_power_mw) < 0 or self.deadline_hours < 1:
            raise ValueError("workload shift, recovery, and deadline values are invalid")
        if not 0 <= self.critical_fraction <= 1:
            raise ValueError("critical workload fraction must be in [0, 1]")


@dataclass(frozen=True)
class ThermalWorkloadPoint:
    hour: int
    cooling_reduction_mw: float
    cooling_rebound_mw: float
    thermal_debt_mwh: float
    workload_shift_mw: float
    workload_recovery_mw: float
    workload_backlog_mwh: float
    oldest_work_age_hours: float
    deadline_violation: bool
    net_reduction_mw: float


@dataclass(frozen=True)
class ThermalWorkloadTrajectory:
    points: tuple[ThermalWorkloadPoint, ...]
    cooling_rebound_peak_mw: float
    workload_rebound_peak_mw: float
    ending_thermal_debt_mwh: float
    ending_workload_backlog_mwh: float
    deadline_violation_hours: int


def simulate_cooling_workload(
    requested_reduction_mw: list[float],
    recovery_opportunity_mw: list[float],
    cooling: CoolingConfig,
    workload: WorkloadConfig,
    *,
    interval_hours: float = 1.0,
) -> ThermalWorkloadTrajectory:
    cooling.validate()
    workload.validate()
    if not requested_reduction_mw or len(requested_reduction_mw) != len(recovery_opportunity_mw):
        raise ValueError("thermal/workload inputs must be non-empty and aligned")
    if min(requested_reduction_mw + recovery_opportunity_mw) < 0:
        raise ValueError("thermal/workload inputs cannot be negative")
    if interval_hours <= 0:
        raise ValueError("interval_hours must be positive")
    thermal_debt = cooling.initial_thermal_debt_mwh
    backlog: list[tuple[int, float]] = []
    points = []
    for hour, (request, opportunity) in enumerate(zip(requested_reduction_mw, recovery_opportunity_mw)):
        cooling_headroom = max(0.0, cooling.maximum_thermal_debt_mwh - thermal_debt)
        cooling_reduction = min(
            request, cooling.maximum_reduction_mw, cooling_headroom / interval_hours
        )
        remaining = request - cooling_reduction
        shift = min(remaining, workload.maximum_shift_mw)
        if shift:
            backlog.append((hour, shift * interval_hours))
        thermal_debt += cooling_reduction * interval_hours
        cooling_rebound = min(
            opportunity,
            cooling.recovery_power_mw,
            thermal_debt / (cooling.recovery_efficiency * interval_hours),
        )
        thermal_debt -= cooling_rebound * cooling.recovery_efficiency * interval_hours
        remaining_opportunity = max(0.0, opportunity - cooling_rebound)
        recovery = min(
            remaining_opportunity,
            workload.recovery_power_mw,
            sum(value for _, value in backlog) / interval_hours,
        )
        left = recovery * interval_hours
        revised = []
        for created, value in backlog:
            used = min(value, left)
            left -= used
            if value - used > 1e-9:
                revised.append((created, value - used))
        backlog = revised
        oldest = (hour - backlog[0][0] + 1) * interval_hours if backlog else 0.0
        deadline = oldest > workload.deadline_hours
        points.append(
            ThermalWorkloadPoint(
                hour, cooling_reduction, cooling_rebound, thermal_debt, shift, recovery,
                sum(value for _, value in backlog), oldest, deadline,
                cooling_reduction + shift - cooling_rebound - recovery,
            )
        )
    return ThermalWorkloadTrajectory(
        points=tuple(points),
        cooling_rebound_peak_mw=max(item.cooling_rebound_mw for item in points),
        workload_rebound_peak_mw=max(item.workload_recovery_mw for item in points),
        ending_thermal_debt_mwh=thermal_debt,
        ending_workload_backlog_mwh=sum(value for _, value in backlog),
        deadline_violation_hours=sum(item.deadline_violation for item in points),
    )
