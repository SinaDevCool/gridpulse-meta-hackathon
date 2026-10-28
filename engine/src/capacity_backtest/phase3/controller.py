"""Bounded feedback controller for digital-twin P/Q setpoints."""

from __future__ import annotations

from dataclasses import dataclass

from .commands import DispatchSetpoint
from .telemetry import PCCMeasurement, TelemetryGate


@dataclass(frozen=True)
class FeedbackCoefficients:
    active_gain: float
    voltage_reactive_gain_mvar_per_kv: float
    damping: float
    target_voltage_kv: float
    reactive_min_mvar: float
    reactive_max_mvar: float

    def validate(self) -> None:
        if min(self.active_gain, self.voltage_reactive_gain_mvar_per_kv) < 0:
            raise ValueError("feedback gains cannot be negative")
        if not 0 < self.damping <= 1 or self.target_voltage_kv <= 0:
            raise ValueError("feedback damping and target voltage are invalid")
        if self.reactive_min_mvar > self.reactive_max_mvar:
            raise ValueError("reactive feedback bounds are reversed")


def calculate_feedback_setpoint(
    measurement: PCCMeasurement,
    gate: TelemetryGate,
    coefficients: FeedbackCoefficients,
    *,
    envelope_limit_mw: float,
    firm_fail_safe_limit_mw: float,
    previous_setpoint: DispatchSetpoint | None,
    elapsed_minutes: float,
    ramp_limit_mw_per_minute: float,
) -> DispatchSetpoint:
    coefficients.validate()
    if min(envelope_limit_mw, firm_fail_safe_limit_mw, elapsed_minutes, ramp_limit_mw_per_minute) < 0:
        raise ValueError("controller limits cannot be negative")
    safe_limit = envelope_limit_mw if gate.accepted else firm_fail_safe_limit_mw
    error = max(0.0, measurement.active_power_mw - safe_limit)
    requested_reduction = error * coefficients.active_gain
    target_active = max(0.0, measurement.active_power_mw - requested_reduction)
    target_active = min(target_active, safe_limit)
    if previous_setpoint is not None:
        maximum_change = elapsed_minutes * ramp_limit_mw_per_minute
        target_active = min(
            max(target_active, previous_setpoint.active_power_limit_mw - maximum_change),
            previous_setpoint.active_power_limit_mw + maximum_change,
        )
    # The electrical envelope is a hard safety bound; ramp smoothing cannot override it.
    target_active = min(target_active, safe_limit)
    mean_voltage = sum(measurement.voltage_kv.values()) / 3
    raw_q = measurement.reactive_power_mvar + (
        coefficients.target_voltage_kv - mean_voltage
    ) * coefficients.voltage_reactive_gain_mvar_per_kv
    reactive = measurement.reactive_power_mvar + coefficients.damping * (
        raw_q - measurement.reactive_power_mvar
    )
    reactive = min(max(reactive, coefficients.reactive_min_mvar), coefficients.reactive_max_mvar)
    return DispatchSetpoint(
        active_power_limit_mw=target_active,
        reactive_power_setpoint_mvar=reactive,
        requested_reduction_mw=max(0.0, measurement.active_power_mw - target_active),
        ramp_limit_mw_per_minute=ramp_limit_mw_per_minute,
    )
