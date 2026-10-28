"""Verify active/reactive delivery and export evidence to Phase 2 credibility."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.phase2.credibility import DeliveryEvidence

from .commands import DispatchCommand
from .telemetry import PCCMeasurement, TelemetryGate


@dataclass(frozen=True)
class DeliveryVerification:
    command_id: str
    resource_id: str
    requested_reduction_mw: float
    delivered_reduction_mw: float
    delivery_ratio: float
    active_within_tolerance: bool
    reactive_within_tolerance: bool
    telemetry_accepted: bool
    passed: bool
    reasons: tuple[str, ...]
    evidence: DeliveryEvidence


def verify_delivery(
    command: DispatchCommand,
    baseline: PCCMeasurement,
    observed: PCCMeasurement,
    observed_gate: TelemetryGate,
    *,
    resource_id: str,
    active_tolerance_mw: float,
    reactive_tolerance_mvar: float,
    response_seconds: float,
) -> DeliveryVerification:
    command.validate()
    baseline.validate()
    observed.validate()
    if baseline.pcc_id != command.pcc_id or observed.pcc_id != command.pcc_id:
        raise ValueError("delivery measurements do not match command PCC")
    if min(active_tolerance_mw, reactive_tolerance_mvar, response_seconds) < 0:
        raise ValueError("delivery tolerances and response time cannot be negative")
    requested = command.setpoint.requested_reduction_mw
    delivered = max(0.0, baseline.active_power_mw - observed.active_power_mw)
    active_ok = delivered + active_tolerance_mw >= requested
    reactive_ok = abs(observed.reactive_power_mvar - command.setpoint.reactive_power_setpoint_mvar) <= reactive_tolerance_mvar
    reasons = []
    if not observed_gate.accepted:
        reasons.append("telemetry_rejected")
    if not active_ok:
        reasons.append("active_non_delivery")
    if not reactive_ok:
        reasons.append("reactive_non_delivery")
    ratio = min(1.0, delivered / requested) if requested else 1.0
    evidence = DeliveryEvidence(
        resource_id=resource_id,
        event_at=observed.timestamp,
        requested_mw=requested,
        delivered_mw=min(requested, delivered),
        response_seconds=response_seconds,
        verified=observed_gate.accepted,
    )
    evidence.validate()
    return DeliveryVerification(
        command.command_id, resource_id, requested, delivered, ratio, active_ok, reactive_ok,
        observed_gate.accepted, not reasons, tuple(reasons), evidence,
    )
