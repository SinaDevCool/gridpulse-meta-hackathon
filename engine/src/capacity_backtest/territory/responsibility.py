"""Conservative geographic DSO and candidate connection-authority resolution."""

from __future__ import annotations

from .contracts import ResponsibilityResult, TerritoryMatch
from .registry import RegistryMatch

EXCEPTION_TYPES = {
    "closed_distribution_network", "private_customer_network", "railway_network",
    "airport_or_industrial_campus", "direct_tso_candidate", "cross_boundary_site",
    "unknown_network_owner",
}


def resolve_responsibility(
    territory: TerritoryMatch,
    registry: RegistryMatch,
    *,
    requested_mw: float,
    exception_flags: tuple[str, ...] = (),
    operator_assigned_connection_id: str | None = None,
    operator_assigned_level: str | None = None,
    operator_evidence_id: str | None = None,
) -> ResponsibilityResult:
    territory.validate()
    if requested_mw <= 0:
        raise ValueError("requested_mw must be positive")
    unknown = set(exception_flags) - EXCEPTION_TYPES
    if unknown:
        raise ValueError(f"unknown network exception flags: {sorted(unknown)}")
    evidence = list(territory.evidence_ids)
    if operator_evidence_id:
        evidence.append(operator_evidence_id)
    if territory.match_status != "matched" or not territory.operator_id:
        return ResponsibilityResult(territory.site_id, None, None, "unknown", "ambiguous",
                                    tuple(exception_flags), True, tuple(evidence))
    if registry.review_required or registry.operator_id is None:
        return ResponsibilityResult(territory.site_id, territory.operator_id, None, "unknown",
                                    "unresolved", tuple(exception_flags), True, tuple(evidence))
    if exception_flags:
        return ResponsibilityResult(territory.site_id, registry.operator_id, None, "unknown",
                                    "requires_operator_study", tuple(exception_flags), True,
                                    tuple(evidence))
    if operator_assigned_connection_id:
        if not operator_evidence_id or operator_assigned_level not in {"distribution", "transmission"}:
            raise ValueError("operator assignment requires evidence and a valid connection level")
        return ResponsibilityResult(
            territory.site_id, registry.operator_id, operator_assigned_connection_id,
            operator_assigned_level, "operator_confirmed", (), False, tuple(evidence),
        )
    # Requested MW may influence study routing, but can never self-assign the TSO.
    return ResponsibilityResult(
        territory.site_id, registry.operator_id, registry.operator_id, "distribution",
        "validated_geographic_match", (), True, tuple(evidence),
    )
