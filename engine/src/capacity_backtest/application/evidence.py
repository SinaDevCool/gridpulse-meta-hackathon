"""Pure transport boundary for deterministic operator-enquiry packages."""

from __future__ import annotations

from typing import Any

from capacity_backtest.data_center.reporting import compose_data_center_enquiry_package

from .facility import ENGINE_VERSION, _fingerprint, _serialize

EVIDENCE_PACKAGE_REQUEST_SCHEMA = "gridpulse-operator-enquiry-package-request-v1"
EVIDENCE_PACKAGE_RESULT_SCHEMA = "gridpulse-operator-enquiry-package-application-result-v1"


def run_evidence_package(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != EVIDENCE_PACKAGE_REQUEST_SCHEMA:
        raise ValueError("unsupported operator-enquiry package request schema")
    artifacts = request.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("evidence package artifacts are required")
    content = compose_data_center_enquiry_package(
        package_id=str(request["package_id"]),
        artifacts=artifacts,
        blockers=tuple(str(value) for value in request.get("blockers", ())),
        assumption_ids=tuple(str(value) for value in request.get("assumption_ids", ())),
    )
    payload = {
        "schema_version": EVIDENCE_PACKAGE_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(request),
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "package": _serialize(content),
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
