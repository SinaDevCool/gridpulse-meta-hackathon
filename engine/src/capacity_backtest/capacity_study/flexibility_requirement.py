"""Build, but never infer from report text, a requirement from a capacity result."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.domain.results import CapacityEnvelopeResult


@dataclass(frozen=True)
class OperatingTerms:
    response_time_seconds: int | None = None
    maximum_event_duration_minutes: int | None = None
    maximum_events_per_day: int | None = None
    maximum_events_per_year: int | None = None
    maximum_annual_event_hours: float | None = None
    minimum_notice_minutes: int | None = None
    recovery_ramp_mw_per_minute: float | None = None
    rebound_limit_mw: float | None = None
    reactive_power_requirement: str | None = None


def build_flexibility_requirement(
    capacity_result: CapacityEnvelopeResult,
    *,
    site_id: str,
    pcc_id: str,
    requested_import_mw: float,
    expected_provenance_fingerprint: str,
    operating_terms: OperatingTerms | None = None,
    assumption_ids: tuple[str, ...] = (),
    capacity_is_lower_bound: bool = False,
) -> FlexibilityRequirement:
    """Derive the planning need from the exact validated capacity envelope version."""

    capacity_result.validate()
    operating_terms = operating_terms or OperatingTerms()
    actual_fingerprint = capacity_result.provenance.fingerprint()
    if actual_fingerprint != expected_provenance_fingerprint:
        raise ValueError("capacity provenance does not match the requested envelope")
    if capacity_result.firm_capacity_mw is None:
        raise ValueError("firm capacity must be known before deriving flexibility")
    conditional = capacity_result.conditional_capacity_mw
    if conditional is None:
        raise ValueError("conditional capacity must be known before deriving flexibility")
    firm = capacity_result.firm_capacity_mw
    required = max(0.0, requested_import_mw - firm)
    feasible = requested_import_mw <= conditional
    blockers: list[str] = []
    if operating_terms.response_time_seconds is None:
        blockers.append("response_time_unknown")
    if operating_terms.maximum_event_duration_minutes is None:
        blockers.append("maximum_event_duration_unknown")
    if not feasible:
        blockers.append("requested_import_exceeds_conditional_envelope")
    truth = coerce_truth_class(capacity_result.truth_class)
    operator_confirmed = truth == TruthClass.OPERATOR_CONFIRMED and capacity_result.capacity_claim
    identity = {
        "capacity_result_id": capacity_result.result_id,
        "capacity_schema": capacity_result.schema_version,
        "provenance": actual_fingerprint,
        "site_id": site_id,
        "pcc_id": pcc_id,
        "requested_import_mw": requested_import_mw,
        "terms": operating_terms.__dict__,
        "assumptions": assumption_ids,
    }
    requirement_id = "flex-" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    requirement = FlexibilityRequirement(
        requirement_id=requirement_id,
        site_id=site_id,
        pcc_id=pcc_id,
        capacity_result_id=capacity_result.result_id,
        capacity_envelope_schema_version=capacity_result.schema_version,
        capacity_provenance_fingerprint=actual_fingerprint,
        requested_import_mw=requested_import_mw,
        firm_limit_mw=firm,
        conditional_limit_mw=conditional,
        required_reduction_mw=required,
        conservative_required_reduction_mw=(requested_import_mw if capacity_is_lower_bound else required),
        response_time_seconds=operating_terms.response_time_seconds,
        maximum_event_duration_minutes=operating_terms.maximum_event_duration_minutes,
        maximum_events_per_day=operating_terms.maximum_events_per_day,
        maximum_events_per_year=operating_terms.maximum_events_per_year,
        maximum_annual_event_hours=operating_terms.maximum_annual_event_hours,
        minimum_notice_minutes=operating_terms.minimum_notice_minutes,
        recovery_ramp_mw_per_minute=operating_terms.recovery_ramp_mw_per_minute,
        rebound_limit_mw=operating_terms.rebound_limit_mw,
        reactive_power_requirement=operating_terms.reactive_power_requirement,
        evidence_cutoff=capacity_result.provenance.evidence_cutoff,
        truth_class=truth,
        operator_confirmed=operator_confirmed,
        capacity_is_lower_bound=capacity_is_lower_bound,
        feasible_within_conditional_envelope=feasible,
        surplus_capacity_mw=max(0.0, conditional - requested_import_mw),
        assumption_ids=assumption_ids,
        blockers=tuple(blockers),
    )
    requirement.validate()
    return requirement
