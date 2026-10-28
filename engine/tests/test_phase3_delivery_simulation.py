from __future__ import annotations

from capacity_backtest.phase3.commands import CommandLedger
from capacity_backtest.phase3.delivery import verify_delivery
from capacity_backtest.phase3.failsafe import FailSafeMachine, OperationalEvent, OperationalState
from capacity_backtest.phase3.simulation import (
    DigitalTwin,
    SimulationEvent,
    SimulationEventKind,
)

from .test_phase3_commands_failsafe import command
from .test_phase3_telemetry_controller import gate, measurement


def successful_verification():
    baseline = measurement()
    observed = measurement(
        measurement_id="m-2", sequence=2, timestamp="2026-01-01T00:00:04+00:00",
        active_power_mw=60, reactive_power_mvar=2,
    )
    return verify_delivery(
        command(), baseline, observed,
        gate(observed, evaluated_at="2026-01-01T00:00:05+00:00", previous_sequence=1),
        resource_id="battery-1", active_tolerance_mw=0.5,
        reactive_tolerance_mvar=0.5, response_seconds=3,
    )


def test_delivery_verification_exports_phase2_credibility_evidence() -> None:
    result = successful_verification()
    assert result.passed
    assert result.delivery_ratio == 1
    assert result.evidence.verified
    assert result.evidence.delivered_mw == 10


def test_delivery_verification_fails_active_reactive_and_telemetry_gates() -> None:
    observed = measurement(
        measurement_id="m-bad", sequence=1, timestamp="2026-01-01T00:00:10+00:00",
        active_power_mw=68, reactive_power_mvar=9,
    )
    result = verify_delivery(
        command(), measurement(), observed,
        gate(observed, evaluated_at="2026-01-01T00:00:20+00:00", previous_sequence=1),
        resource_id="battery-1", active_tolerance_mw=0.5,
        reactive_tolerance_mvar=0.5, response_seconds=20,
    )
    assert not result.passed
    assert set(result.reasons) == {
        "telemetry_rejected", "active_non_delivery", "reactive_non_delivery"
    }
    assert result.evidence.verified is False


def test_digital_twin_success_path_is_deterministic_and_tamper_evident() -> None:
    def run():
        machine = FailSafeMachine()
        machine.apply(OperationalEvent.ARM, "2025-12-31T23:59:59+00:00")
        twin = DigitalTwin(CommandLedger({"auth-1"}, 5), machine)
        events = [
            SimulationEvent("command", "2026-01-01T00:00:00+00:00", SimulationEventKind.COMMAND, {"command": command()}),
            SimulationEvent("ack", "2026-01-01T00:00:03+00:00", SimulationEventKind.ACKNOWLEDGEMENT, {"command_id": "c-1", "accepted": True}),
            SimulationEvent("delivery", "2026-01-01T00:00:05+00:00", SimulationEventKind.DELIVERY, {"verification": successful_verification()}),
        ]
        return twin.replay(events)

    first, second = run(), run()
    assert first.final_state == OperationalState.ARMED.value
    assert first.final_hash == second.final_hash
    assert first.automatic_live_dispatch_authorized is False
    assert all(entry.previous_hash == ("0" * 64 if index == 0 else first.entries[index - 1].entry_hash) for index, entry in enumerate(first.entries))


def test_digital_twin_fault_drives_fail_safe() -> None:
    machine = FailSafeMachine()
    machine.apply(OperationalEvent.ARM, "2025-12-31T23:59:59+00:00")
    twin = DigitalTwin(CommandLedger({"auth-1"}, 2), machine)
    result = twin.replay([
        SimulationEvent("command", "2026-01-01T00:00:00+00:00", SimulationEventKind.COMMAND, {"command": command()}),
        SimulationEvent("ack", "2026-01-01T00:00:03+00:00", SimulationEventKind.ACKNOWLEDGEMENT, {"command_id": "c-1", "accepted": True}),
    ])
    assert result.final_state == OperationalState.SAFE_LIMIT.value
    assert result.command_timeouts == 1
    assert result.fail_safe_entries == 1
