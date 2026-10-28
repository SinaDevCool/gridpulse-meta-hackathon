"""Structured operator-data blockers for capacity screening."""

from __future__ import annotations

from .contracts import BlockerSeverity, CandidatePCC, CapacityBlocker, PCCStatus

TECHNICAL_BLOCKERS = (
    (
        "short_circuit_study_missing",
        "Short-circuit level has not been validated.",
        "DSO/TSO short-circuit study",
    ),
    (
        "protection_study_missing",
        "Protection coordination has not been validated.",
        "DSO/TSO protection study",
    ),
    (
        "harmonic_study_missing",
        "Harmonic and flicker limits have not been validated.",
        "operator power-quality study",
    ),
    (
        "dynamic_stability_missing",
        "Dynamic stability has not been validated.",
        "operator dynamic study",
    ),
    (
        "reactive_requirements_missing",
        "Final reactive-power requirements are unknown.",
        "connection agreement",
    ),
)


def capacity_blockers(
    pcc: CandidatePCC,
    *,
    operator_topology: bool,
    operator_ratings: bool,
    operator_loading: bool,
    operator_queue: bool,
    operator_contingencies: bool,
) -> tuple[CapacityBlocker, ...]:
    rows = []
    if pcc.status != PCCStatus.OPERATOR_CONFIRMED:
        rows.append(
            (
                "pcc_unconfirmed",
                "The modeled PCC is not operator-confirmed.",
                "DSO/TSO confirmation",
            )
        )
    for present, code, message, source in (
        (
            operator_topology,
            "topology_reconstructed",
            "Complete operator topology is unavailable.",
            "DSO/TSO network model",
        ),
        (
            operator_ratings,
            "ratings_reconstructed",
            "Electrical ratings contain reconstructed assumptions.",
            "DSO/TSO equipment data",
        ),
        (
            operator_loading,
            "nodal_loading_reconstructed",
            "Nodal loading is reconstructed from aggregate observations.",
            "DSO/TSO nodal history",
        ),
        (
            operator_queue,
            "queue_reconstructed",
            "Committed queue and reservations are not operator-complete.",
            "DSO/TSO queue",
        ),
        (
            operator_contingencies,
            "contingencies_unreviewed",
            "The N-1 set has not been operator-reviewed.",
            "DSO/TSO contingency policy",
        ),
    ):
        if not present:
            rows.append((code, message, source))
    rows.extend(TECHNICAL_BLOCKERS)
    blockers = tuple(
        CapacityBlocker(code, BlockerSeverity.OPERATOR_CONFIRMATION_REQUIRED, message, source)
        for code, message, source in rows
    )
    for blocker in blockers:
        blocker.validate()
    return blockers
