"""Explicit source admission decisions; availability is not admissibility."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdmissionDecision:
    source_id: str
    scope: str
    machine_readable: bool
    publication_time_available: bool
    revision_history_reconstructable: bool
    stable_identity: bool
    empty_distinguishable_from_failure: bool
    units_validated: bool
    reuse_permitted: bool
    admitted_for_training: bool
    reason: str

    def validate(self) -> None:
        prerequisites = (
            self.machine_readable,
            self.publication_time_available,
            self.revision_history_reconstructable,
            self.stable_identity,
            self.empty_distinguishable_from_failure,
            self.units_validated,
            self.reuse_permitted,
        )
        if self.admitted_for_training and not all(prerequisites):
            raise ValueError(f"{self.source_id} cannot be admitted with failed prerequisites")
        if not self.reason:
            raise ValueError("admission decision requires a reason")


def require_training_admission(decision: AdmissionDecision) -> None:
    decision.validate()
    if not decision.admitted_for_training:
        raise ValueError(
            f"source {decision.source_id} is not admitted for training: {decision.reason}"
        )
