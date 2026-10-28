"""Shadow-only integration of canonical plans with the existing Phase 3 twin."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase3.commands import (
    CommandLedger,
    DispatchCommand,
    DispatchSetpoint,
)
from capacity_backtest.phase3.delivery import DeliveryVerification, verify_delivery
from capacity_backtest.phase3.failsafe import FailSafeMachine, OperationalEvent
from capacity_backtest.phase3.simulation import (
    DigitalTwin,
    SimulationEvent,
    SimulationEventKind,
    SimulationResult,
)
from capacity_backtest.phase3.telemetry import PCCMeasurement, TelemetryGate

from .optimizer import FacilityOptimizationResult


@dataclass(frozen=True)
class ShadowReplayResult:
    verification: DeliveryVerification
    simulation: SimulationResult
    plan_observation_residual_mw: float
    shadow_only: bool = True
    automatic_live_dispatch_authorized: bool = False
    schema_version: str = "gridpulse-shadow-replay-v1"


def build_shadow_command(
    optimization: FacilityOptimizationResult,
    requirement: FlexibilityRequirement,
    *,
    issued_at: str,
    effective_at: str,
    expires_at: str,
) -> DispatchCommand:
    if optimization.status != "optimal" or optimization.facility is None:
        raise ValueError("only a replay-verified optimal result can become a shadow command")
    command = DispatchCommand(
        f"shadow-{optimization.model_fingerprint[:16]}",
        optimization.model_fingerprint,
        requirement.pcc_id,
        (optimization.facility.facility_id,),
        issued_at,
        effective_at,
        expires_at,
        "shadow-only",
        requirement.capacity_result_id,
        DispatchSetpoint(
            max(0.0, requirement.requested_import_mw - requirement.required_reduction_mw),
            0.0,
            requirement.required_reduction_mw,
            requirement.recovery_ramp_mw_per_minute or 0.0,
        ),
    )
    command.validate()
    return command


def run_shadow_replay(
    command: DispatchCommand,
    baseline: PCCMeasurement,
    observed: PCCMeasurement,
    observed_gate: TelemetryGate,
    *,
    resource_id: str,
    active_tolerance_mw: float,
    reactive_tolerance_mvar: float,
    response_seconds: float,
    armed_at: str,
    acknowledged_at: str,
) -> ShadowReplayResult:
    """Replay an inert command; this function has no transport or device capability."""

    verification = verify_delivery(
        command, baseline, observed, observed_gate, resource_id=resource_id,
        active_tolerance_mw=active_tolerance_mw,
        reactive_tolerance_mvar=reactive_tolerance_mvar,
        response_seconds=response_seconds,
    )
    machine = FailSafeMachine()
    machine.apply(OperationalEvent.ARM, armed_at)
    twin = DigitalTwin(CommandLedger({command.authorization_id}, max(1.0, response_seconds * 2)), machine)
    events = [
        SimulationEvent(f"{command.command_id}-issue", command.issued_at, SimulationEventKind.COMMAND, {"command": command}),
        SimulationEvent(f"{command.command_id}-ack", acknowledged_at, SimulationEventKind.ACKNOWLEDGEMENT, {"command_id": command.command_id, "accepted": True}),
        SimulationEvent(f"{command.command_id}-delivery", observed.timestamp, SimulationEventKind.DELIVERY, {"verification": verification}),
    ]
    simulation = twin.replay(events)
    residual = abs(command.setpoint.active_power_limit_mw - observed.active_power_mw)
    return ShadowReplayResult(verification, simulation, residual)
