from capacity_backtest.data_center.optimizer import optimize_facility_flexibility
from capacity_backtest.data_center.shadow import build_shadow_command, run_shadow_replay

from .test_data_center_optimizer import inputs
from .test_phase3_commands_failsafe import command
from .test_phase3_telemetry_controller import gate, measurement


def test_shadow_replay_uses_existing_twin_and_never_authorizes_live_dispatch() -> None:
    observed = measurement(
        measurement_id="m-2", sequence=2, timestamp="2026-01-01T00:00:04+00:00",
        active_power_mw=60, reactive_power_mvar=2,
    )
    result = run_shadow_replay(
        command(), measurement(), observed,
        gate(observed, evaluated_at="2026-01-01T00:00:05+00:00", previous_sequence=1),
        resource_id="battery-1", active_tolerance_mw=0.5, reactive_tolerance_mvar=0.5,
        response_seconds=3, armed_at="2025-12-31T23:59:59+00:00",
        acknowledged_at="2026-01-01T00:00:03+00:00",
    )
    assert result.verification.passed
    assert result.simulation.final_state == "armed"
    assert result.shadow_only and not result.automatic_live_dispatch_authorized


def test_optimizer_maps_only_to_inert_shadow_command() -> None:
    values = inputs()
    result = optimize_facility_flexibility(**values)
    created = build_shadow_command(
        result, values["requirement"], issued_at="2025-12-31T23:00:00+00:00",
        effective_at="2026-01-01T00:00:00+00:00", expires_at="2026-01-01T01:00:00+00:00",
    )
    assert created.authorization_id == "shadow-only"
