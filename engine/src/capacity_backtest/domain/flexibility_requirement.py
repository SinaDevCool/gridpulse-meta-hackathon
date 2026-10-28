"""Canonical planning contract derived from an existing capacity envelope."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.contracts import TruthClass, coerce_truth_class

from .base import DomainContract, parse_aware_timestamp, require_non_empty

FLEXIBILITY_REQUIREMENT_SCHEMA_VERSION = "gridpulse-flexibility-requirement-v1"


@dataclass(frozen=True)
class FlexibilityRequirement(DomainContract):
    requirement_id: str
    site_id: str
    pcc_id: str
    capacity_result_id: str
    capacity_envelope_schema_version: str
    capacity_provenance_fingerprint: str
    requested_import_mw: float
    firm_limit_mw: float
    conditional_limit_mw: float
    required_reduction_mw: float
    conservative_required_reduction_mw: float
    response_time_seconds: int | None
    maximum_event_duration_minutes: int | None
    maximum_events_per_day: int | None
    maximum_events_per_year: int | None
    maximum_annual_event_hours: float | None
    minimum_notice_minutes: int | None
    recovery_ramp_mw_per_minute: float | None
    rebound_limit_mw: float | None
    reactive_power_requirement: str | None
    evidence_cutoff: str
    truth_class: TruthClass
    operator_confirmed: bool
    capacity_is_lower_bound: bool
    feasible_within_conditional_envelope: bool
    surplus_capacity_mw: float = 0.0
    assumption_ids: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    schema_version: str = FLEXIBILITY_REQUIREMENT_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != FLEXIBILITY_REQUIREMENT_SCHEMA_VERSION:
            raise ValueError("unsupported flexibility-requirement schema")
        for value, name in (
            (self.requirement_id, "requirement_id"),
            (self.site_id, "site_id"),
            (self.pcc_id, "pcc_id"),
            (self.capacity_result_id, "capacity_result_id"),
            (self.capacity_envelope_schema_version, "capacity_envelope_schema_version"),
        ):
            require_non_empty(value, name)
        if len(self.capacity_provenance_fingerprint) != 64:
            raise ValueError("capacity provenance fingerprint must be SHA-256")
        if any(c not in "0123456789abcdefABCDEF" for c in self.capacity_provenance_fingerprint):
            raise ValueError("capacity provenance fingerprint must be SHA-256")
        parse_aware_timestamp(self.evidence_cutoff, "evidence_cutoff")
        truth = coerce_truth_class(self.truth_class)
        powers = (
            self.requested_import_mw,
            self.firm_limit_mw,
            self.conditional_limit_mw,
            self.required_reduction_mw,
            self.conservative_required_reduction_mw,
            self.surplus_capacity_mw,
        )
        if any(value < 0 for value in powers):
            raise ValueError("flexibility-requirement powers cannot be negative")
        if self.firm_limit_mw > self.conditional_limit_mw:
            raise ValueError("firm capacity cannot exceed conditional capacity")
        expected_surplus = max(0.0, self.conditional_limit_mw - self.requested_import_mw)
        if abs(self.surplus_capacity_mw - expected_surplus) > 1e-9:
            raise ValueError("conditional surplus must be represented explicitly")
        expected_reduction = max(0.0, self.requested_import_mw - self.firm_limit_mw)
        if abs(self.required_reduction_mw - expected_reduction) > 1e-9:
            raise ValueError("required reduction must be derived from the firm limit")
        if self.conservative_required_reduction_mw < self.required_reduction_mw:
            raise ValueError("conservative reduction cannot be less than required reduction")
        if self.feasible_within_conditional_envelope != (
            self.requested_import_mw <= self.conditional_limit_mw
        ):
            raise ValueError("conditional-envelope feasibility is inconsistent")
        optional_non_negative = (
            self.response_time_seconds,
            self.maximum_event_duration_minutes,
            self.maximum_events_per_day,
            self.maximum_events_per_year,
            self.maximum_annual_event_hours,
            self.minimum_notice_minutes,
            self.recovery_ramp_mw_per_minute,
            self.rebound_limit_mw,
        )
        if any(value is not None and value < 0 for value in optional_non_negative):
            raise ValueError("operating terms cannot be negative")
        if self.operator_confirmed and truth != TruthClass.OPERATOR_CONFIRMED:
            raise ValueError("only operator-confirmed evidence can set operator_confirmed")
