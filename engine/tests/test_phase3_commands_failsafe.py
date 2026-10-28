from __future__ import annotations

import pytest

from capacity_backtest.phase3.commands import (
    CommandLedger,
    CommandStatus,
    DispatchCommand,
    DispatchSetpoint,
)
from capacity_backtest.phase3.failsafe import FailSafeMachine, OperationalEvent, OperationalState


def command(**changes) -> DispatchCommand:
    values = {
        "command_id": "c-1", "idempotency_key": "i-1", "pcc_id": "pcc-1",
        "resource_ids": ("battery-1",), "issued_at": "2026-01-01T00:00:00+00:00",
        "effective_at": "2026-01-01T00:00:01+00:00", "expires_at": "2026-01-01T01:00:00+00:00",
        "authorization_id": "auth-1", "envelope_result_id": "result-1",
        "setpoint": DispatchSetpoint(60, 2, 10, 5),
    }
    values.update(changes)
    return DispatchCommand(**values)


def test_command_ledger_is_authorized_idempotent_and_acknowledged() -> None:
    ledger = CommandLedger({"auth-1"}, 5)
    first = ledger.issue(command())
    assert ledger.issue(command()) is first
    acknowledged = ledger.acknowledge("c-1", "2026-01-01T00:00:03+00:00", accepted=True)
    assert acknowledged.status == CommandStatus.ACKNOWLEDGED
    assert ledger.complete("c-1", "2026-01-01T00:05:00+00:00").status == CommandStatus.COMPLETED


def test_command_rejects_missing_authorization_and_times_out() -> None:
    with pytest.raises(PermissionError):
        CommandLedger(set(), 5).issue(command())
    ledger = CommandLedger({"auth-1"}, 5)
    ledger.issue(command())
    expired = ledger.expire("2026-01-01T00:00:06+00:00")
    assert expired[0].status == CommandStatus.TIMED_OUT


def test_command_rejects_impossible_acknowledgement_and_completion_times() -> None:
    ledger = CommandLedger({"auth-1"}, 5)
    ledger.issue(command())
    with pytest.raises(ValueError, match="precede"):
        ledger.acknowledge("c-1", "2025-12-31T23:59:59+00:00", accepted=True)
    acknowledged = ledger.acknowledge("c-1", "2026-01-01T00:00:03+00:00", accepted=True)
    assert acknowledged.status == CommandStatus.ACKNOWLEDGED
    with pytest.raises(ValueError, match="after expiry"):
        ledger.complete("c-1", "2026-01-01T02:00:00+00:00")


def test_fail_safe_state_machine_reaches_safe_limit_and_lockout() -> None:
    machine = FailSafeMachine()
    machine.apply(OperationalEvent.ARM, "2026-01-01T00:00:00+00:00")
    machine.apply(OperationalEvent.COMMAND_ACKNOWLEDGED, "2026-01-01T00:00:01+00:00")
    machine.apply(OperationalEvent.DELIVERY_FAILED, "2026-01-01T00:00:02+00:00")
    assert machine.state == OperationalState.SAFE_LIMIT
    assert not machine.conditional_dispatch_allowed
    machine.apply(OperationalEvent.MANUAL_LOCKOUT, "2026-01-01T00:00:03+00:00")
    assert machine.state == OperationalState.LOCKED_OUT
    machine.apply(OperationalEvent.RESET, "2026-01-01T00:00:04+00:00")
    assert machine.state == OperationalState.DISARMED
