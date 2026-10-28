"""Territory/PCC admission gate in front of physical and operator-confirmed studies."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain.scenario import StudyScenario

from .confirmation import ConfirmationAuthorization
from .contracts import ResponsibilityResult, SiteLocation, TerritoryMatch


@dataclass(frozen=True)
class TerritoryAdmissibility:
    public_screening_allowed: bool
    physical_nodal_run_allowed: bool
    operator_confirmed_claim_allowed: bool
    status: str
    blockers: tuple[str, ...]


def evaluate_territory_admissibility(
    scenario: StudyScenario,
    location: SiteLocation,
    territory: TerritoryMatch,
    responsibility: ResponsibilityResult,
    authorization: ConfirmationAuthorization | None,
    *,
    network_operator_id: str | None,
    candidate_pcc_id: str | None,
) -> TerritoryAdmissibility:
    scenario.validate(); location.validate(); territory.validate(); responsibility.validate()
    blockers: list[str] = []
    if scenario.site_location_id != location.site_id or territory.site_id != location.site_id or responsibility.site_id != location.site_id:
        blockers.append("site identity mismatch")
    if territory.match_status != "matched":
        blockers.append("territory match is not unambiguous")
    if responsibility.status not in {"validated_geographic_match", "operator_confirmed"}:
        blockers.append("connection responsibility is unresolved")
    expected = responsibility.candidate_connection_operator_id
    if network_operator_id and expected and network_operator_id != expected:
        blockers.append("network model operator conflicts with responsibility result")
    pcc = bool(candidate_pcc_id and scenario.candidate_bus_id == candidate_pcc_id)
    confirmation_references = bool(
        scenario.operator_confirmation_id and scenario.candidate_pcc_evidence_id
    )
    confirmed_pcc = bool(
        authorization and authorization.pcc_confirmed and pcc and confirmation_references
    )
    physical = not blockers and confirmed_pcc and bool(network_operator_id)
    operator_claim = bool(physical and authorization and authorization.capacity_claim_allowed)
    if coerce_truth_class(scenario.truth_class) == TruthClass.OPERATOR_CONFIRMED and not operator_claim:
        blockers.append("operator-confirmed truth requested without study-outcome authorization")
    status = "operator_confirmed" if operator_claim else "physical_ready" if physical else "screening_only"
    return TerritoryAdmissibility(True, physical, operator_claim, status, tuple(dict.fromkeys(blockers)))
