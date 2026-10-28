"""Deterministic replayable operational digital twin."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

from .commands import CommandLedger, CommandStatus, DispatchCommand
from .delivery import DeliveryVerification
from .failsafe import FailSafeMachine, OperationalEvent
from .telemetry import PCCMeasurement, TelemetryGate


class SimulationEventKind(str, Enum):
    TELEMETRY = "telemetry"
    COMMAND = "command"
    ACKNOWLEDGEMENT = "acknowledgement"
    DELIVERY = "delivery"
    ENVELOPE_STALE = "envelope_stale"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    MANUAL_LOCKOUT = "manual_lockout"


@dataclass(frozen=True)
class SimulationEvent:
    event_id: str
    at: str
    kind: SimulationEventKind
    payload: dict[str, object]


@dataclass(frozen=True)
class SimulationLogEntry:
    sequence: int
    event_id: str
    at: str
    kind: str
    prior_state: str
    current_state: str
    outcome: str
    previous_hash: str
    entry_hash: str


@dataclass(frozen=True)
class SimulationResult:
    final_state: str
    entries: tuple[SimulationLogEntry, ...]
    final_hash: str
    delivery_failures: int
    command_timeouts: int
    fail_safe_entries: int
    automatic_live_dispatch_authorized: bool = False


class DigitalTwin:
    def __init__(self, ledger: CommandLedger, fail_safe: FailSafeMachine):
        self.ledger = ledger
        self.fail_safe = fail_safe
        self.measurements: dict[str, tuple[PCCMeasurement, TelemetryGate]] = {}
        self.commands: dict[str, DispatchCommand] = {}
        self.deliveries: dict[str, DeliveryVerification] = {}

    def replay(self, events: list[SimulationEvent]) -> SimulationResult:
        if not events or len({event.event_id for event in events}) != len(events):
            raise ValueError("simulation events must be non-empty with unique identities")
        if [event.at for event in events] != sorted(event.at for event in events):
            raise ValueError("simulation events must be chronological")
        entries = []
        previous_hash = "0" * 64
        delivery_failures = timeouts = safe_entries = 0
        for sequence, event in enumerate(events):
            prior = self.fail_safe.state.value
            outcome = self._apply(event)
            if outcome == "delivery_failed":
                delivery_failures += 1
            if outcome == "ack_timeout":
                timeouts += 1
            current = self.fail_safe.state.value
            safe_entries += int(current in {"safe_limit", "locked_out"} and prior != current)
            content = {
                "sequence": sequence, "event_id": event.event_id, "at": event.at,
                "kind": event.kind.value, "prior_state": prior, "current_state": current,
                "outcome": outcome, "previous_hash": previous_hash,
            }
            entry_hash = hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            entry = SimulationLogEntry(
                sequence, event.event_id, event.at, event.kind.value, prior, current,
                outcome, previous_hash, entry_hash,
            )
            entries.append(entry)
            previous_hash = entry_hash
        return SimulationResult(
            self.fail_safe.state.value, tuple(entries), previous_hash,
            delivery_failures, timeouts, safe_entries,
        )

    def _apply(self, event: SimulationEvent) -> str:
        payload = event.payload
        if event.kind == SimulationEventKind.TELEMETRY:
            measurement = payload.get("measurement")
            gate = payload.get("gate")
            if not isinstance(measurement, PCCMeasurement) or not isinstance(gate, TelemetryGate):
                raise ValueError("telemetry simulation event requires measurement and gate")
            self.measurements[measurement.measurement_id] = (measurement, gate)
            if not gate.accepted:
                self.fail_safe.apply(OperationalEvent.TELEMETRY_INVALID, event.at)
                return "telemetry_invalid"
            return "telemetry_accepted"
        if event.kind == SimulationEventKind.COMMAND:
            command = payload.get("command")
            if not isinstance(command, DispatchCommand):
                raise ValueError("command simulation event requires a command")
            self.ledger.issue(command)
            self.commands[command.command_id] = command
            return "command_pending"
        if event.kind == SimulationEventKind.ACKNOWLEDGEMENT:
            command_id = str(payload["command_id"])
            accepted = bool(payload.get("accepted", False))
            record = self.ledger.acknowledge(command_id, event.at, accepted=accepted)
            if record.status == CommandStatus.TIMED_OUT:
                self.fail_safe.apply(OperationalEvent.ACK_TIMEOUT, event.at)
                return "ack_timeout"
            if record.status == CommandStatus.REJECTED:
                self.fail_safe.apply(OperationalEvent.DELIVERY_FAILED, event.at, "command_rejected")
                return "command_rejected"
            self.fail_safe.apply(OperationalEvent.COMMAND_ACKNOWLEDGED, event.at)
            return "command_acknowledged"
        if event.kind == SimulationEventKind.DELIVERY:
            verification = payload.get("verification")
            if not isinstance(verification, DeliveryVerification):
                raise ValueError("delivery simulation event requires verification")
            self.deliveries[verification.command_id] = verification
            if not verification.passed:
                self.fail_safe.apply(OperationalEvent.DELIVERY_FAILED, event.at)
                return "delivery_failed"
            self.ledger.complete(verification.command_id, event.at)
            self.fail_safe.apply(OperationalEvent.COMMAND_COMPLETED, event.at)
            return "delivery_verified"
        mapping = {
            SimulationEventKind.ENVELOPE_STALE: OperationalEvent.ENVELOPE_STALE,
            SimulationEventKind.RESOURCE_UNAVAILABLE: OperationalEvent.RESOURCE_UNAVAILABLE,
            SimulationEventKind.MANUAL_LOCKOUT: OperationalEvent.MANUAL_LOCKOUT,
        }
        transition = mapping.get(event.kind)
        if transition is None:
            raise ValueError("unsupported simulation event")
        self.fail_safe.apply(transition, event.at)
        return transition.value
