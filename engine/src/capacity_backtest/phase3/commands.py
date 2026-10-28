"""Authorized, idempotent dispatch command and acknowledgement lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from capacity_backtest.domain.base import parse_aware_timestamp


@dataclass(frozen=True)
class DispatchSetpoint:
    active_power_limit_mw: float
    reactive_power_setpoint_mvar: float
    requested_reduction_mw: float
    ramp_limit_mw_per_minute: float

    def validate(self) -> None:
        if min(self.active_power_limit_mw, self.requested_reduction_mw, self.ramp_limit_mw_per_minute) < 0:
            raise ValueError("active, reduction, and ramp setpoints cannot be negative")


@dataclass(frozen=True)
class DispatchCommand:
    command_id: str
    idempotency_key: str
    pcc_id: str
    resource_ids: tuple[str, ...]
    issued_at: str
    effective_at: str
    expires_at: str
    authorization_id: str
    envelope_result_id: str
    setpoint: DispatchSetpoint

    def validate(self) -> None:
        if not all((self.command_id, self.idempotency_key, self.pcc_id, self.authorization_id, self.envelope_result_id)):
            raise ValueError("command identity, authorization, PCC, and envelope are required")
        issued = parse_aware_timestamp(self.issued_at, "command issued_at")
        effective = parse_aware_timestamp(self.effective_at, "command effective_at")
        expires = parse_aware_timestamp(self.expires_at, "command expires_at")
        if not issued <= effective < expires:
            raise ValueError("command times must satisfy issued <= effective < expires")
        if not self.resource_ids or len(self.resource_ids) != len(set(self.resource_ids)):
            raise ValueError("commands require unique resources")
        self.setpoint.validate()


class CommandStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass(frozen=True)
class CommandRecord:
    command: DispatchCommand
    status: CommandStatus
    acknowledged_at: str | None = None
    reason: str | None = None


class CommandLedger:
    def __init__(self, authorized_ids: set[str], acknowledgement_timeout_seconds: float):
        if acknowledgement_timeout_seconds <= 0:
            raise ValueError("acknowledgement timeout must be positive")
        self.authorized_ids = set(authorized_ids)
        self.timeout = acknowledgement_timeout_seconds
        self._records: dict[str, CommandRecord] = {}
        self._idempotency: dict[str, str] = {}

    def issue(self, command: DispatchCommand) -> CommandRecord:
        command.validate()
        if command.authorization_id not in self.authorized_ids:
            raise PermissionError("dispatch authorization is not active")
        prior_id = self._idempotency.get(command.idempotency_key)
        if prior_id:
            prior = self._records[prior_id]
            if prior.command != command:
                raise ValueError("idempotency key was reused for a different command")
            return prior
        if command.command_id in self._records:
            raise ValueError("command identity must be unique")
        record = CommandRecord(command, CommandStatus.PENDING)
        self._records[command.command_id] = record
        self._idempotency[command.idempotency_key] = command.command_id
        return record

    def acknowledge(self, command_id: str, at: str, *, accepted: bool, reason: str | None = None) -> CommandRecord:
        record = self._require_pending(command_id)
        acknowledged = parse_aware_timestamp(at, "acknowledged_at")
        issued = parse_aware_timestamp(record.command.issued_at, "issued_at")
        expires = parse_aware_timestamp(record.command.expires_at, "expires_at")
        if acknowledged < issued:
            raise ValueError("acknowledgement cannot precede command issue")
        if acknowledged >= expires:
            return self._replace(record, CommandStatus.TIMED_OUT, at, "command_expired")
        if (acknowledged - issued).total_seconds() > self.timeout:
            return self._replace(record, CommandStatus.TIMED_OUT, at, "acknowledgement_timeout")
        status = CommandStatus.ACKNOWLEDGED if accepted else CommandStatus.REJECTED
        return self._replace(record, status, at, reason)

    def expire(self, evaluated_at: str) -> tuple[CommandRecord, ...]:
        evaluated = parse_aware_timestamp(evaluated_at, "evaluated_at")
        changed = []
        for record in list(self._records.values()):
            if record.status != CommandStatus.PENDING:
                continue
            issued = parse_aware_timestamp(record.command.issued_at, "issued_at")
            if (evaluated - issued).total_seconds() > self.timeout:
                changed.append(self._replace(record, CommandStatus.TIMED_OUT, evaluated_at, "acknowledgement_timeout"))
        return tuple(changed)

    def complete(self, command_id: str, at: str) -> CommandRecord:
        record = self._records.get(command_id)
        if record is None or record.status != CommandStatus.ACKNOWLEDGED:
            raise ValueError("only acknowledged commands can complete")
        completed = parse_aware_timestamp(at, "completed_at")
        acknowledged = parse_aware_timestamp(record.acknowledged_at or "", "acknowledged_at")
        expires = parse_aware_timestamp(record.command.expires_at, "expires_at")
        if completed < acknowledged:
            raise ValueError("completion cannot precede acknowledgement")
        if completed >= expires:
            raise ValueError("command cannot complete after expiry")
        return self._replace(record, CommandStatus.COMPLETED, at, None)

    def record(self, command_id: str) -> CommandRecord:
        if command_id not in self._records:
            raise ValueError("unknown command")
        return self._records[command_id]

    def _require_pending(self, command_id: str) -> CommandRecord:
        record = self.record(command_id)
        if record.status != CommandStatus.PENDING:
            raise ValueError("command is no longer pending")
        return record

    def _replace(self, record: CommandRecord, status: CommandStatus, at: str, reason: str | None) -> CommandRecord:
        revised = CommandRecord(record.command, status, at, reason)
        self._records[record.command.command_id] = revised
        return revised
