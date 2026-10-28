"""Stable transport boundary from a canonical capacity result to a flexibility requirement."""

from __future__ import annotations

from typing import Any

from capacity_backtest.capacity_study.flexibility_requirement import (
    OperatingTerms,
    build_flexibility_requirement,
)
from capacity_backtest.contracts import TruthClass
from capacity_backtest.domain.evidence import EvidenceReference, RunProvenance
from capacity_backtest.domain.results import CapacityEnvelopeResult

from .facility import _fingerprint, _serialize

CAPACITY_REQUIREMENT_REQUEST_SCHEMA = "gridpulse-capacity-requirement-request-v1"
CAPACITY_REQUIREMENT_RESULT_SCHEMA = "gridpulse-capacity-requirement-application-result-v1"


def _evidence(row: dict[str, Any]) -> EvidenceReference:
    values = dict(row)
    values["truth_class"] = TruthClass(values["truth_class"])
    values["limitations"] = tuple(values.get("limitations", ()))
    return EvidenceReference(**values)


def run_capacity_requirement(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != CAPACITY_REQUIREMENT_REQUEST_SCHEMA:
        raise ValueError("unsupported capacity-requirement request schema")
    capacity_values = dict(request["capacity_result"])
    provenance_values = dict(capacity_values.pop("provenance"))
    provenance_values["evidence"] = tuple(
        _evidence(row) for row in provenance_values.get("evidence", ())
    )
    provenance = RunProvenance(**provenance_values)
    capacity_values["truth_class"] = TruthClass(capacity_values["truth_class"])
    capacity_values["unknown_constraints"] = tuple(capacity_values.get("unknown_constraints", ()))
    capacity = CapacityEnvelopeResult(provenance=provenance, **capacity_values)
    terms = OperatingTerms(**request.get("operating_terms", {}))
    requirement = build_flexibility_requirement(
        capacity,
        site_id=str(request["site_id"]),
        pcc_id=str(request["pcc_id"]),
        requested_import_mw=float(request["requested_import_mw"]),
        expected_provenance_fingerprint=str(request["expected_provenance_fingerprint"]),
        operating_terms=terms,
        assumption_ids=tuple(request.get("assumption_ids", ())),
        capacity_is_lower_bound=bool(request.get("capacity_is_lower_bound", False)),
    )
    payload = {
        "schema_version": CAPACITY_REQUIREMENT_RESULT_SCHEMA,
        "input_fingerprint": _fingerprint(request),
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "requirement": _serialize(requirement),
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
