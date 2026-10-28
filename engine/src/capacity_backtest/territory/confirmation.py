"""Scope-limited authorization from reviewed operator responsibility evidence."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.domain.base import parse_aware_timestamp

from .contracts import OperatorResponsibilityConfirmation, ResponsibilityResult


@dataclass(frozen=True)
class ConfirmationAuthorization:
    responsibility_confirmed: bool
    pcc_confirmed: bool
    study_outcome_confirmed: bool
    contractual_connection_confirmed: bool
    capacity_claim_allowed: bool
    reason: str


def authorize_confirmation(
    confirmation: OperatorResponsibilityConfirmation,
    responsibility: ResponsibilityResult,
    *,
    as_of: str,
    expected_site_id: str,
) -> ConfirmationAuthorization:
    confirmation.validate()
    responsibility.validate()
    instant = parse_aware_timestamp(as_of, "as_of")
    start = parse_aware_timestamp(confirmation.valid_from, "valid_from")
    end = parse_aware_timestamp(confirmation.valid_to, "valid_to") if confirmation.valid_to else None
    if confirmation.site_id != expected_site_id or responsibility.site_id != expected_site_id:
        raise ValueError("operator confirmation site identity mismatch")
    if responsibility.geographic_dso_id and confirmation.operator_id not in {
        responsibility.geographic_dso_id, responsibility.candidate_connection_operator_id,
    }:
        raise ValueError("operator confirmation identity conflicts with responsibility result")
    if instant < start or (end is not None and instant >= end):
        return ConfirmationAuthorization(False, False, False, False, False,
                                         "operator confirmation is not valid at the study time")
    scope = confirmation.confirmation_scope
    responsibility_confirmed = scope in {
        "responsible_operator", "candidate_pcc_assigned", "connection_study_outcome",
        "contractual_connection",
    }
    pcc_confirmed = scope in {
        "candidate_pcc_assigned", "connection_study_outcome", "contractual_connection",
    }
    study = scope in {"connection_study_outcome", "contractual_connection"}
    contractual = scope == "contractual_connection"
    return ConfirmationAuthorization(
        responsibility_confirmed, pcc_confirmed, study, contractual,
        study, f"authorization limited to operator evidence scope: {scope}",
    )
