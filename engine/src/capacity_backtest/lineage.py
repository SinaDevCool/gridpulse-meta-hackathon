"""Artifact lineage verification."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .contracts import TruthClass, coerce_truth_class


def artifact_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_derived_manifest(
    output_path: Path,
    input_paths: list[Path],
    *,
    transformation_version: str,
    limitations: list[str],
    truth_class: TruthClass | str = TruthClass.UNKNOWN,
    evidence_cutoff: str | None = None,
    code_version: str = "unknown",
    assumption_set_id: str = "unspecified",
    solver_name: str = "not_applicable",
    solver_version: str = "not_applicable",
) -> Path:
    canonical_truth = coerce_truth_class(truth_class)
    payload = {
        "schema_version": "gridpulse-derived-artifact-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact": str(output_path),
        "artifact_sha256": artifact_sha256(output_path),
        "inputs": [
            {"path": str(path), "sha256": artifact_sha256(path)} for path in input_paths
        ],
        "transformation_version": transformation_version,
        "truth_class": canonical_truth.value,
        "capacity_claim": False,
        "evidence_cutoff": evidence_cutoff,
        "code_version": code_version,
        "assumption_set_id": assumption_set_id,
        "solver": {"name": solver_name, "version": solver_version},
        "limitations": limitations,
    }
    manifest = output_path.with_suffix(output_path.suffix + ".manifest.json")
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest
