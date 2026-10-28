"""Versioned network-evidence contracts for mock and future operator models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import TruthClass, coerce_truth_class

NETWORK_SCHEMA_VERSION = "grid-network-evidence-v1"
REQUIRED_PROVENANCE = {
    "source_id",
    "source_url",
    "retrieved_at",
    "snapshot_hash",
    "licence",
    "geographic_resolution",
}


@dataclass(frozen=True)
class NetworkEvidencePackage:
    schema_version: str
    model_id: str
    model_version: str
    truth_class: TruthClass
    effective_at: str
    buses: tuple[dict[str, Any], ...]
    branches: tuple[dict[str, Any], ...]
    transformers: tuple[dict[str, Any], ...]
    switches: tuple[dict[str, Any], ...]
    operational_limits: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]
    operator_validated: bool = False

    def validate(self) -> None:
        if self.schema_version != NETWORK_SCHEMA_VERSION:
            raise ValueError("unsupported network schema version")
        if not self.model_id or not self.model_version:
            raise ValueError("model identity and version are required")
        effective = datetime.fromisoformat(self.effective_at.replace("Z", "+00:00"))
        if effective.tzinfo is None or effective.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")
        missing = REQUIRED_PROVENANCE - set(self.provenance)
        if missing or any(not self.provenance.get(name) for name in REQUIRED_PROVENANCE):
            raise ValueError(f"network provenance is incomplete: {sorted(missing)}")
        bus_ids = [str(item.get("id", "")) for item in self.buses]
        if not bus_ids or any(not value for value in bus_ids) or len(bus_ids) != len(set(bus_ids)):
            raise ValueError("buses require unique non-empty identifiers")
        known = set(bus_ids)
        asset_ids: list[str] = []
        for branch in self.branches:
            asset_ids.append(str(branch.get("id", "")))
            if {str(branch.get("from_bus")), str(branch.get("to_bus"))} - known:
                raise ValueError("branch refers to an unknown bus")
        for transformer in self.transformers:
            asset_ids.append(str(transformer.get("id", "")))
            if {str(transformer.get("hv_bus")), str(transformer.get("lv_bus"))} - known:
                raise ValueError("transformer refers to an unknown bus")
        if any(not value for value in asset_ids) or len(asset_ids) != len(set(asset_ids)):
            raise ValueError("network assets require unique non-empty identifiers")
        for limit in self.operational_limits:
            if str(limit.get("asset_id")) not in set(asset_ids):
                raise ValueError("operational limit refers to an unknown asset")
            if limit.get("value") is None or not limit.get("unit"):
                raise ValueError("operational limits require value and unit")
        if self.truth_class == TruthClass.OPERATOR_CONFIRMED and not self.operator_validated:
            raise ValueError("operator-confirmed network evidence requires explicit validation")
        if self.truth_class == TruthClass.SYNTHETIC_BENCHMARK and self.operator_validated:
            raise ValueError("synthetic network evidence cannot be operator validated")

    def fingerprint(self) -> str:
        self.validate()
        return hashlib.sha256(
            json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "truth_class": self.truth_class.value,
            "effective_at": self.effective_at,
            "buses": list(self.buses),
            "branches": list(self.branches),
            "transformers": list(self.transformers),
            "switches": list(self.switches),
            "operational_limits": list(self.operational_limits),
            "provenance": self.provenance,
            "operator_validated": self.operator_validated,
            "capacity_claim": False,
            "available_capacity_mw": None,
        }


def load_network_package(path: Path) -> NetworkEvidencePackage:
    """Load JSON only after strict identity, unit, timestamp and truth-class validation."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    package = NetworkEvidencePackage(
        schema_version=str(payload.get("schema_version", "")),
        model_id=str(payload.get("model_id", "")),
        model_version=str(payload.get("model_version", "")),
        truth_class=coerce_truth_class(str(payload.get("truth_class", "unknown"))),
        effective_at=str(payload.get("effective_at", "")),
        buses=tuple(payload.get("buses", [])),
        branches=tuple(payload.get("branches", [])),
        transformers=tuple(payload.get("transformers", [])),
        switches=tuple(payload.get("switches", [])),
        operational_limits=tuple(payload.get("operational_limits", [])),
        provenance=dict(payload.get("provenance", {})),
        operator_validated=bool(payload.get("operator_validated", False)),
    )
    package.validate()
    return package
