"""Evidence identity and reproducible run provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from capacity_backtest.contracts import TruthClass, coerce_truth_class

from .base import DomainContract, parse_aware_timestamp, require_non_empty

EVIDENCE_SCHEMA_VERSION = "gridpulse-evidence-reference-v1"
PROVENANCE_SCHEMA_VERSION = "gridpulse-run-provenance-v1"


@dataclass(frozen=True)
class EvidenceReference(DomainContract):
    evidence_id: str
    source_id: str
    snapshot_hash: str
    retrieved_at: str
    truth_class: TruthClass
    source_locator: str
    limitations: tuple[str, ...] = ()
    schema_version: str = EVIDENCE_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported evidence-reference schema")
        for value, name in ((self.evidence_id, "evidence_id"), (self.source_id, "source_id")):
            require_non_empty(value, name)
        parse_aware_timestamp(self.retrieved_at, "retrieved_at")
        coerce_truth_class(self.truth_class)
        if len(self.snapshot_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in self.snapshot_hash):
            raise ValueError("snapshot_hash must be a SHA-256 hexadecimal digest")
        require_non_empty(self.source_locator, "source_locator")


@dataclass(frozen=True)
class RunProvenance(DomainContract):
    run_id: str
    created_at: str
    evidence_cutoff: str
    code_version: str
    assumption_set_id: str
    solver_name: str
    solver_version: str
    input_hashes: dict[str, str]
    evidence: tuple[EvidenceReference, ...] = ()
    schema_version: str = PROVENANCE_SCHEMA_VERSION
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if self.schema_version != PROVENANCE_SCHEMA_VERSION:
            raise ValueError("unsupported run-provenance schema")
        for value, name in (
            (self.run_id, "run_id"),
            (self.code_version, "code_version"),
            (self.assumption_set_id, "assumption_set_id"),
            (self.solver_name, "solver_name"),
            (self.solver_version, "solver_version"),
        ):
            require_non_empty(value, name)
        created = parse_aware_timestamp(self.created_at, "created_at")
        cutoff = parse_aware_timestamp(self.evidence_cutoff, "evidence_cutoff")
        if cutoff > created:
            raise ValueError("evidence_cutoff cannot be later than created_at")
        if not self.input_hashes:
            raise ValueError("input_hashes must not be empty")
        for name, digest in self.input_hashes.items():
            require_non_empty(name, "input hash name")
            if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
                raise ValueError(f"input hash {name!r} is not SHA-256")
        for item in self.evidence:
            item.validate()

    def fingerprint(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
