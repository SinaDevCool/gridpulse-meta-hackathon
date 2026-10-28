"""Operational readiness gate layered over Phase 2 dependable capacity."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.phase2.capacity import DependableCapacityAssessment


@dataclass(frozen=True)
class OperationalReadiness:
    ready_for_digital_twin_dispatch: bool
    live_dispatch_authorized: bool
    blockers: tuple[str, ...]
    firm_fail_safe_limit_mw: float
    dependable_conditional_limit_mw: float
    schema_version: str = "gridpulse-operational-readiness-v1"


def assess_operational_readiness(
    capacity: DependableCapacityAssessment,
    *,
    telemetry_configured: bool,
    command_channel_configured: bool,
    acknowledgement_supported: bool,
    fail_safe_tested: bool,
    delivery_verification_configured: bool,
    operator_authorization_id: str | None = None,
) -> OperationalReadiness:
    capacity.validate()
    blockers = list(capacity.blockers)
    requirements = {
        "telemetry_not_configured": telemetry_configured,
        "command_channel_not_configured": command_channel_configured,
        "acknowledgement_not_supported": acknowledgement_supported,
        "fail_safe_not_tested": fail_safe_tested,
        "delivery_verification_not_configured": delivery_verification_configured,
    }
    blockers.extend(name for name, passed in requirements.items() if not passed)
    digital_twin_ready = not blockers
    operator_capacity_confirmed = (
        coerce_truth_class(capacity.phase1.result.truth_class) == TruthClass.OPERATOR_CONFIRMED
        and capacity.phase1.result.capacity_claim
    )
    live_authorized = (
        digital_twin_ready and bool(operator_authorization_id) and operator_capacity_confirmed
    )
    if not operator_authorization_id:
        blockers.append("operator_dispatch_authorization_missing")
    if not operator_capacity_confirmed:
        blockers.append("operator_confirmed_capacity_missing")
    firm = capacity.phase1.result.firm_capacity_mw or 0.0
    return OperationalReadiness(
        digital_twin_ready,
        live_authorized,
        tuple(dict.fromkeys(blockers)),
        firm,
        capacity.dependable_conditional_capacity_mw,
    )
