"""Fail-closed validation and reconciliation for confidential operator evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_INTAKE = {
    "schema_version",
    "operator",
    "dataset_id",
    "retrieved_at",
    "effective_from",
    "geographic_resolution",
    "units",
    "permitted_uses",
    "prohibited_uses",
    "files",
}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_operator_intake(manifest_path: Path, repository_root: Path) -> dict[str, Any]:
    """Validate a confidential intake manifest without copying data into Git."""
    manifest_path = manifest_path.resolve()
    repository_root = repository_root.resolve()
    if manifest_path.is_relative_to(repository_root):
        raise ValueError("confidential operator intake must be stored outside the Git repository")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_INTAKE - payload.keys())
    if missing:
        raise ValueError(f"operator intake manifest missing fields: {missing}")
    if not payload["units"] or not payload["geographic_resolution"]:
        raise ValueError("units and geographic resolution must be explicit")
    validated = []
    for item in payload["files"]:
        if not {"path", "sha256", "content_type"} <= item.keys():
            raise ValueError("each operator file requires path, sha256, and content_type")
        path = (manifest_path.parent / item["path"]).resolve()
        if not path.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError("operator file escapes the confidential intake directory")
        if not path.is_file() or _digest(path) != item["sha256"]:
            raise ValueError(f"operator file missing or hash mismatch: {item['path']}")
        validated.append({"path": item["path"], "sha256": item["sha256"]})
    return {
        "status": "validated",
        "truth_class": "operator-model-unvalidated",
        "operator_confirmed": False,
        "available_capacity_mw": None,
        "files": validated,
        "warnings": ["Validation establishes integrity, not network accuracy or capacity."],
    }


def reconcile_connection_outcomes(
    predictions: list[dict[str, Any]], outcomes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare frozen predictions with later decisions without claiming confirmation."""
    by_request = {row["request_id"]: row for row in outcomes}
    rows = []
    for prediction in predictions:
        outcome = by_request.get(prediction["request_id"])
        if outcome is None:
            continue
        if prediction["issued_at"] >= outcome["decision_at"]:
            continue
        if prediction.get("identity_method") in {"nearest", "proximity"}:
            continue
        predicted = prediction.get("predicted_conditional_mw")
        offered = outcome.get("offered_conditional_mw")
        rows.append(
            {
                "request_id": prediction["request_id"],
                "issued_at": prediction["issued_at"],
                "decision_at": outcome["decision_at"],
                "error_mw": None if predicted is None or offered is None else predicted - offered,
            }
        )
    errors = [row["error_mw"] for row in rows if row["error_mw"] is not None]
    return {
        "schema_version": "operator-reconciliation-v1",
        "truth_class": "operator-reconciled" if rows else "operator-model-unvalidated",
        "operator_confirmed": False,
        "available_capacity_mw": None,
        "matched_requests": len(rows),
        "mean_absolute_error_mw": (
            sum(abs(value) for value in errors) / len(errors) if errors else None
        ),
        "rows": rows,
        "warnings": ["Historical reconciliation is not operator confirmation of live capacity."],
    }
