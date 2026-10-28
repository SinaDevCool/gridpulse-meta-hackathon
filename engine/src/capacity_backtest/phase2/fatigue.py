"""Operational fatigue and cumulative flexibility-burden gates."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import ceil, isfinite


@dataclass(frozen=True)
class FatigueLimits:
    maximum_consecutive_event_hours: int
    maximum_event_hours_per_rolling_day: int
    maximum_events_per_rolling_week: int
    annual_shifted_energy_mwh: float
    annual_battery_cycles: float
    minimum_cooldown_hours: int

    def validate(self) -> None:
        if min(
            self.maximum_consecutive_event_hours,
            self.maximum_event_hours_per_rolling_day,
            self.maximum_events_per_rolling_week,
            self.minimum_cooldown_hours,
        ) < 0 or min(self.annual_shifted_energy_mwh, self.annual_battery_cycles) < 0:
            raise ValueError("fatigue limits cannot be negative")


@dataclass(frozen=True)
class FatigueAssessment:
    passed: bool
    event_count: int
    event_hours: float
    maximum_consecutive_hours: float
    maximum_rolling_day_hours: float
    maximum_rolling_week_events: int
    cooldown_violations: int
    shifted_energy_mwh: float
    battery_cycles: float
    violations: tuple[str, ...]


def evaluate_fatigue(
    activated_mw: list[float],
    battery_cycles: float,
    limits: FatigueLimits,
    *, interval_hours: float = 1.0,
) -> FatigueAssessment:
    limits.validate()
    if not isfinite(interval_hours) or not 0 < interval_hours <= 1:
        raise ValueError("fatigue interval must be finite and in (0, 1]")
    if not activated_mw or min(activated_mw) < 0 or battery_cycles < 0:
        raise ValueError("fatigue inputs must be non-empty and non-negative")
    active = [value > 1e-9 for value in activated_mw]
    starts = [index for index, value in enumerate(active) if value and (index == 0 or not active[index - 1])]
    consecutive = maximum = 0
    for value in active:
        consecutive = consecutive + 1 if value else 0
        maximum = max(maximum, consecutive)
    rolling_day = max(sum(active[start : start + ceil(24 / interval_hours)]) for start in range(len(active))) * interval_hours
    rolling_week_events = max(
        sum(start <= event < start + ceil(168 / interval_hours) for event in starts) for start in range(len(active))
    )
    cooldown_violations = 0
    for prior, current in pairwise(starts):
        prior_end = prior
        while prior_end + 1 < len(active) and active[prior_end + 1]:
            prior_end += 1
        cooldown_violations += int((current - prior_end - 1) * interval_hours < limits.minimum_cooldown_hours)
    maximum *= interval_hours
    shifted = sum(activated_mw) * interval_hours
    violations = []
    if maximum > limits.maximum_consecutive_event_hours:
        violations.append("maximum_consecutive_event_hours")
    if rolling_day > limits.maximum_event_hours_per_rolling_day:
        violations.append("maximum_event_hours_per_rolling_day")
    if rolling_week_events > limits.maximum_events_per_rolling_week:
        violations.append("maximum_events_per_rolling_week")
    if cooldown_violations:
        violations.append("minimum_cooldown_hours")
    if shifted > limits.annual_shifted_energy_mwh:
        violations.append("annual_shifted_energy_mwh")
    if battery_cycles > limits.annual_battery_cycles:
        violations.append("annual_battery_cycles")
    return FatigueAssessment(
        passed=not violations,
        event_count=len(starts), event_hours=sum(active) * interval_hours, maximum_consecutive_hours=maximum,
        maximum_rolling_day_hours=rolling_day, maximum_rolling_week_events=rolling_week_events,
        cooldown_violations=cooldown_violations, shifted_energy_mwh=shifted,
        battery_cycles=battery_cycles, violations=tuple(violations),
    )
