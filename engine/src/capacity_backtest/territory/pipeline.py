"""End-to-end, evidence-cutoff-safe site-to-operator resolution."""

from __future__ import annotations

from dataclasses import asdict

from .contracts import SiteLocation, TerritorySnapshot
from .geometry import match_site_to_territories
from .registry import OperatorRegistryEntry, reconcile_operator
from .responsibility import resolve_responsibility
from .sources import select_territories_as_known


def resolve_site_operator(
    location: SiteLocation,
    territories: list[TerritorySnapshot],
    registry_entries: tuple[OperatorRegistryEntry, ...] | list[OperatorRegistryEntry],
    *,
    decision_time: str,
    evidence_cutoff: str,
    requested_mw: float,
    boundary_review_m: float = 500,
    exception_flags: tuple[str, ...] = (),
) -> dict[str, object]:
    selected = select_territories_as_known(
        territories, decision_time=decision_time, evidence_cutoff=evidence_cutoff
    )
    if not selected:
        return {
            "schema_version": "gridpulse-territory-resolution-v1",
            "site_id": location.site_id,
            "status": "historically_unavailable",
            "geographic_dso": None,
            "candidate_connection_operator": None,
            "public_screening_allowed": True,
            "physical_nodal_run_allowed": False,
            "operator_confirmed_claim_allowed": False,
            "limitations": ["No territory evidence was available at the historical cutoff"],
        }
    territory_match = match_site_to_territories(
        location, selected, boundary_review_m=boundary_review_m
    )
    matched = next(
        (item for item in selected if item.territory_id == territory_match.territory_id), None
    )
    registry_match = reconcile_operator(
        registry_entries,
        canonical_id=matched.operator_id if matched else None,
        name=matched.operator_name if matched else None,
    )
    responsibility = resolve_responsibility(
        territory_match, registry_match, requested_mw=requested_mw,
        exception_flags=exception_flags,
    )
    limitations = [
        "Geographic DSO identification does not establish connection voltage or capacity",
        "No operator-assigned PCC",
        "No operator-confirmed capacity",
    ]
    return {
        "schema_version": "gridpulse-territory-resolution-v1",
        "site_id": location.site_id,
        "status": responsibility.status,
        "territory_match": asdict(territory_match),
        "registry_match": asdict(registry_match),
        "responsibility": asdict(responsibility),
        "geographic_dso": registry_match.operator_id,
        "candidate_connection_operator": responsibility.candidate_connection_operator_id,
        "public_screening_allowed": True,
        "physical_nodal_run_allowed": False,
        "operator_confirmed_claim_allowed": False,
        "limitations": limitations,
    }
