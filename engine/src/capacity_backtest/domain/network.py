"""Time-aligned electrical network capacity envelopes."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.contracts import TruthClass, coerce_truth_class

from .base import DomainContract, parse_aware_timestamp, require_non_empty

NETWORK_ENVELOPE_SCHEMA_VERSION = "gridpulse-network-envelope-v1"


@dataclass(frozen=True)
class NetworkEnvelope(DomainContract):
    envelope_id: str
    network_model_id: str
    candidate_bus_id: str
    timestamps: tuple[str, ...]
    n0_import_mw: tuple[float, ...]
    n1_import_mw: tuple[float, ...]
    truth_class: TruthClass
    binding_constraints: tuple[str | None, ...] = ()
    schema_version: str = NETWORK_ENVELOPE_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != NETWORK_ENVELOPE_SCHEMA_VERSION:
            raise ValueError("unsupported network-envelope schema")
        for value, name in (
            (self.envelope_id, "envelope_id"),
            (self.network_model_id, "network_model_id"),
            (self.candidate_bus_id, "candidate_bus_id"),
        ):
            require_non_empty(value, name)
        coerce_truth_class(self.truth_class)
        size = len(self.timestamps)
        if not size or len(self.n0_import_mw) != size or len(self.n1_import_mw) != size:
            raise ValueError("network-envelope series must be non-empty and aligned")
        if self.binding_constraints and len(self.binding_constraints) != size:
            raise ValueError("binding constraints must align with envelope timestamps")
        parsed = [parse_aware_timestamp(value, "envelope timestamp") for value in self.timestamps]
        if parsed != sorted(parsed) or len(parsed) != len(set(parsed)):
            raise ValueError("network-envelope timestamps must be unique and chronological")
        for n0, n1 in zip(self.n0_import_mw, self.n1_import_mw):
            if n0 < 0 or n1 < 0:
                raise ValueError("network capacity cannot be negative")
            if n1 > n0 + 1e-9:
                raise ValueError("N-1 capacity cannot exceed N-0 capacity")
