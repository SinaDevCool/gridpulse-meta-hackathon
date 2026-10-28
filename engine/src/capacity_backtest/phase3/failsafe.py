"""Explicit operational fail-safe state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from capacity_backtest.domain.base import parse_aware_timestamp


class OperationalState(str, Enum):
    DISARMED = "disarmed"
    ARMED = "armed"
    DISPATCHING = "dispatching"
    DEGRADED = "degraded"
    SAFE_LIMIT = "safe_limit"
    LOCKED_OUT = "locked_out"


class OperationalEvent(str, Enum):
    ARM = "arm"
    DISARM = "disarm"
    COMMAND_ACKNOWLEDGED = "command_acknowledged"
    COMMAND_COMPLETED = "command_completed"
    TELEMETRY_INVALID = "telemetry_invalid"
    ACK_TIMEOUT = "ack_timeout"
    DELIVERY_FAILED = "delivery_failed"
    ENVELOPE_STALE = "envelope_stale"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    MANUAL_LOCKOUT = "manual_lockout"
    RESET = "reset"


@dataclass(frozen=True)
class StateTransition:
    at: str
    event: OperationalEvent
    prior: OperationalState
    current: OperationalState
    reason: str


class FailSafeMachine:
    def __init__(self) -> None:
        self.state = OperationalState.DISARMED
        self.transitions: list[StateTransition] = []

    def apply(self, event: OperationalEvent, at: str, reason: str = "") -> StateTransition:
        parse_aware_timestamp(at, "state transition time")
        prior = self.state
        if event == OperationalEvent.MANUAL_LOCKOUT:
            current = OperationalState.LOCKED_OUT
        elif event == OperationalEvent.RESET:
            if prior != OperationalState.LOCKED_OUT:
                raise ValueError("reset is allowed only from locked out")
            current = OperationalState.DISARMED
        elif event == OperationalEvent.DISARM:
            current = OperationalState.DISARMED
        elif event == OperationalEvent.ARM:
            if prior != OperationalState.DISARMED:
                raise ValueError("arm is allowed only from disarmed")
            current = OperationalState.ARMED
        elif event == OperationalEvent.COMMAND_ACKNOWLEDGED:
            if prior not in {OperationalState.ARMED, OperationalState.DEGRADED}:
                raise ValueError("dispatch acknowledgement requires armed or degraded state")
            current = OperationalState.DISPATCHING
        elif event == OperationalEvent.COMMAND_COMPLETED:
            if prior != OperationalState.DISPATCHING:
                raise ValueError("only dispatching can complete")
            current = OperationalState.ARMED
        elif event in {OperationalEvent.TELEMETRY_INVALID, OperationalEvent.RESOURCE_UNAVAILABLE}:
            if prior in {OperationalState.DISARMED, OperationalState.LOCKED_OUT}:
                current = prior
            else:
                current = OperationalState.DEGRADED
        elif event in {
            OperationalEvent.ACK_TIMEOUT,
            OperationalEvent.DELIVERY_FAILED,
            OperationalEvent.ENVELOPE_STALE,
        }:
            current = OperationalState.SAFE_LIMIT if prior != OperationalState.LOCKED_OUT else prior
        else:
            raise ValueError("unsupported operational transition")
        self.state = current
        transition = StateTransition(at, event, prior, current, reason or event.value)
        self.transitions.append(transition)
        return transition

    @property
    def conditional_dispatch_allowed(self) -> bool:
        return self.state in {OperationalState.ARMED, OperationalState.DISPATCHING}
