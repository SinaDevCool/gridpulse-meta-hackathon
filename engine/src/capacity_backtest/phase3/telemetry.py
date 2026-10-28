"""PCC telemetry identity, electrical plausibility, freshness, and sequence gates."""

from __future__ import annotations

import math
from dataclasses import dataclass

from capacity_backtest.domain.base import parse_aware_timestamp

PHASES = ("a", "b", "c")


@dataclass(frozen=True)
class PCCMeasurement:
    measurement_id: str
    pcc_id: str
    timestamp: str
    sequence: int
    voltage_kv: dict[str, float]
    current_a: dict[str, float]
    active_power_mw: float
    reactive_power_mvar: float
    frequency_hz: float
    quality: str = "valid"
    source: str = "digital_twin"

    def validate(self) -> None:
        if not self.measurement_id or not self.pcc_id or not self.source:
            raise ValueError("measurement identity, PCC, and source are required")
        parse_aware_timestamp(self.timestamp, "measurement timestamp")
        if self.sequence < 0:
            raise ValueError("measurement sequence cannot be negative")
        if set(self.voltage_kv) != set(PHASES) or set(self.current_a) != set(PHASES):
            raise ValueError("PCC telemetry requires A/B/C voltage and current")
        if min(self.voltage_kv.values()) <= 0 or min(self.current_a.values()) < 0:
            raise ValueError("PCC voltage must be positive and current cannot be negative")
        if not 40 <= self.frequency_hz <= 60:
            raise ValueError("PCC frequency is electrically implausible")
        if self.quality not in {"valid", "estimated", "suspect", "invalid"}:
            raise ValueError("unsupported telemetry quality")


@dataclass(frozen=True)
class TelemetryGate:
    accepted: bool
    age_seconds: float
    voltage_unbalance_fraction: float
    current_unbalance_fraction: float
    apparent_power_mva: float
    power_factor: float
    reasons: tuple[str, ...]


def _unbalance(values: dict[str, float]) -> float:
    mean = sum(values.values()) / len(values)
    return max(abs(value - mean) / mean for value in values.values()) if mean else 0.0


def assess_telemetry(
    measurement: PCCMeasurement,
    *,
    evaluated_at: str,
    previous_sequence: int | None,
    maximum_age_seconds: float,
    voltage_limits_kv: tuple[float, float],
    current_limit_a: float,
    maximum_unbalance_fraction: float,
    minimum_power_factor: float,
) -> TelemetryGate:
    measurement.validate()
    evaluated = parse_aware_timestamp(evaluated_at, "evaluated_at")
    measured = parse_aware_timestamp(measurement.timestamp, "measurement timestamp")
    age = (evaluated - measured).total_seconds()
    if maximum_age_seconds < 0 or current_limit_a <= 0:
        raise ValueError("telemetry limits are invalid")
    if voltage_limits_kv[0] <= 0 or voltage_limits_kv[0] >= voltage_limits_kv[1]:
        raise ValueError("voltage limits are invalid")
    voltage_unbalance = _unbalance(measurement.voltage_kv)
    current_unbalance = _unbalance(measurement.current_a)
    apparent = math.hypot(measurement.active_power_mw, measurement.reactive_power_mvar)
    power_factor = abs(measurement.active_power_mw) / apparent if apparent else 1.0
    reasons = []
    if age < 0:
        reasons.append("future_timestamp")
    if age > maximum_age_seconds:
        reasons.append("stale")
    if previous_sequence is not None and measurement.sequence <= previous_sequence:
        reasons.append("non_monotonic_sequence")
    if measurement.quality != "valid":
        reasons.append(f"quality_{measurement.quality}")
    if min(measurement.voltage_kv.values()) < voltage_limits_kv[0] or max(measurement.voltage_kv.values()) > voltage_limits_kv[1]:
        reasons.append("voltage_limit")
    if max(measurement.current_a.values()) > current_limit_a:
        reasons.append("current_limit")
    if max(voltage_unbalance, current_unbalance) > maximum_unbalance_fraction:
        reasons.append("phase_unbalance")
    if power_factor + 1e-9 < minimum_power_factor:
        reasons.append("power_factor")
    return TelemetryGate(
        not reasons, age, voltage_unbalance, current_unbalance, apparent, power_factor,
        tuple(reasons),
    )
