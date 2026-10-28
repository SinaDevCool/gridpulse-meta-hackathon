"""Three-phase active/reactive capability and unbalance validation."""

from __future__ import annotations

import math
from dataclasses import dataclass

PHASES = ("a", "b", "c")


@dataclass(frozen=True)
class PhasePowerSpecification:
    active_power_mw: dict[str, float]
    reactive_power_mvar: dict[str, float]
    maximum_phase_unbalance_fraction: float
    minimum_power_factor: float
    reactive_min_mvar: float
    reactive_max_mvar: float
    control_mode: str = "power_factor"

    def validate(self) -> None:
        if set(self.active_power_mw) != set(PHASES) or set(self.reactive_power_mvar) != set(PHASES):
            raise ValueError("phase power requires exactly phases a, b, and c")
        if any(value < 0 for value in self.active_power_mw.values()):
            raise ValueError("phase active power cannot be negative")
        if not 0 <= self.maximum_phase_unbalance_fraction < 1:
            raise ValueError("maximum phase unbalance must be in [0, 1)")
        if not 0 < self.minimum_power_factor <= 1:
            raise ValueError("minimum power factor must be in (0, 1]")
        if self.reactive_min_mvar > self.reactive_max_mvar:
            raise ValueError("reactive capability bounds are reversed")
        if self.control_mode not in {"power_factor", "fixed_q", "voltage_control"}:
            raise ValueError("unsupported reactive control mode")


@dataclass(frozen=True)
class PhasePowerAssessment:
    passed: bool
    total_active_power_mw: float
    total_reactive_power_mvar: float
    apparent_power_mva: float
    power_factor: float
    phase_unbalance_fraction: float
    violations: tuple[str, ...]


def validate_phase_power(specification: PhasePowerSpecification) -> PhasePowerAssessment:
    specification.validate()
    active = sum(specification.active_power_mw.values())
    reactive = sum(specification.reactive_power_mvar.values())
    mean_phase = active / 3
    unbalance = max(
        (abs(value - mean_phase) / mean_phase if mean_phase else 0.0)
        for value in specification.active_power_mw.values()
    )
    apparent = math.hypot(active, reactive)
    power_factor = active / apparent if apparent else 1.0
    violations = []
    if unbalance > specification.maximum_phase_unbalance_fraction:
        violations.append("phase_unbalance")
    if power_factor + 1e-9 < specification.minimum_power_factor:
        violations.append("minimum_power_factor")
    if not specification.reactive_min_mvar <= reactive <= specification.reactive_max_mvar:
        violations.append("reactive_capability")
    return PhasePowerAssessment(
        not violations, active, reactive, apparent, power_factor, unbalance, tuple(violations)
    )
