from __future__ import annotations

from capacity_backtest.phase3.commands import DispatchSetpoint
from capacity_backtest.phase3.controller import FeedbackCoefficients, calculate_feedback_setpoint
from capacity_backtest.phase3.telemetry import PCCMeasurement, assess_telemetry


def measurement(**changes) -> PCCMeasurement:
    values = {
        "measurement_id": "m-1", "pcc_id": "pcc-1",
        "timestamp": "2026-01-01T00:00:00+00:00", "sequence": 1,
        "voltage_kv": {"a": 20, "b": 20, "c": 20},
        "current_a": {"a": 1000, "b": 1000, "c": 1000},
        "active_power_mw": 70, "reactive_power_mvar": 5, "frequency_hz": 50,
    }
    values.update(changes)
    return PCCMeasurement(**values)


def gate(value=None, **changes):
    settings = {
        "evaluated_at": "2026-01-01T00:00:02+00:00", "previous_sequence": 0,
        "maximum_age_seconds": 5, "voltage_limits_kv": (19, 21),
        "current_limit_a": 2000, "maximum_unbalance_fraction": 0.1,
        "minimum_power_factor": 0.95,
    }
    settings.update(changes)
    return assess_telemetry(value or measurement(), **settings)


def coefficients():
    return FeedbackCoefficients(1, 2, 0.5, 20, -10, 10)


def test_valid_pcc_telemetry_passes_and_controller_uses_conditional_limit() -> None:
    accepted = gate()
    assert accepted.accepted
    result = calculate_feedback_setpoint(
        measurement(), accepted, coefficients(), envelope_limit_mw=60,
        firm_fail_safe_limit_mw=50, previous_setpoint=None, elapsed_minutes=1,
        ramp_limit_mw_per_minute=20,
    )
    assert result.active_power_limit_mw == 60
    assert result.requested_reduction_mw == 10


def test_stale_or_bad_sequence_telemetry_forces_firm_limit() -> None:
    rejected = gate(
        evaluated_at="2026-01-01T00:00:10+00:00", previous_sequence=1
    )
    assert not rejected.accepted
    assert set(rejected.reasons) >= {"stale", "non_monotonic_sequence"}
    result = calculate_feedback_setpoint(
        measurement(), rejected, coefficients(), envelope_limit_mw=60,
        firm_fail_safe_limit_mw=50, previous_setpoint=None, elapsed_minutes=1,
        ramp_limit_mw_per_minute=20,
    )
    assert result.active_power_limit_mw == 50


def test_controller_respects_active_ramp_and_reactive_bounds() -> None:
    prior = DispatchSetpoint(65, 0, 5, 2)
    value = measurement(voltage_kv={"a": 18, "b": 18, "c": 18})
    result = calculate_feedback_setpoint(
        value, gate(), coefficients(), envelope_limit_mw=40, firm_fail_safe_limit_mw=40,
        previous_setpoint=prior, elapsed_minutes=1, ramp_limit_mw_per_minute=2,
    )
    assert result.active_power_limit_mw == 40
    assert result.reactive_power_setpoint_mvar <= 10
