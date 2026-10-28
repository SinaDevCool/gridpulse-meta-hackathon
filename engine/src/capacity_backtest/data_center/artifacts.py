"""Portable, immutable dataset/model/release manifests; no training during serving."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from capacity_backtest.domain.base import parse_aware_timestamp


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    source: str
    license: str
    evidence_cutoff: str
    content_sha256: str
    unit_boundaries: dict[str, str]
    transformation_version: str
    train_ids: tuple[str, ...]
    validation_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    truth_class: str

    def validate(self) -> None:
        parse_aware_timestamp(self.evidence_cutoff, "dataset cutoff")
        if not all(
            (
                self.dataset_id,
                self.source,
                self.license,
                self.transformation_version,
                self.unit_boundaries,
            )
        ):
            raise ValueError("dataset provenance, licence and measurement boundaries are required")
        if not re.fullmatch(r"[a-f0-9]{64}", self.content_sha256):
            raise ValueError("dataset content requires SHA-256")
        splits = (self.train_ids, self.validation_ids, self.test_ids)
        if any(not rows or len(set(rows)) != len(rows) for rows in splits):
            raise ValueError("nonempty unique execution splits are required")
        if any(set(splits[i]) & set(splits[j]) for i in range(3) for j in range(i + 1, 3)):
            raise ValueError("dataset splits overlap")
        if self.truth_class not in {"synthetic_demonstration", "measured", "operator_confirmed"}:
            raise ValueError("unsupported dataset provenance")


def chronological_dataset_manifest(
    *, dataset_id: str, source: str, license: str, content: bytes,
    execution_windows: tuple[tuple[str, str, str], ...], evidence_cutoff: str,
    train_end: str, validation_end: str, unit_boundaries: dict[str, str],
    transformation_version: str, truth_class: str,
) -> DatasetManifest:
    """Wrap existing normalized adapters in identity-disjoint, cutoff-safe splits.

    Windows are (execution ID, start, end). A boundary-crossing execution is
    rejected rather than split between training and evaluation. No network I/O.
    """
    if not content or len(content) > 16 * 1024 * 1024 or not 3 <= len(execution_windows) <= 100_000:
        raise ValueError("dataset exceeds bounded offline capture size")
    cutoff = parse_aware_timestamp(evidence_cutoff, "evidence cutoff")
    train_stop = parse_aware_timestamp(train_end, "training end")
    validation_stop = parse_aware_timestamp(validation_end, "validation end")
    if not train_stop < validation_stop < cutoff:
        raise ValueError("chronological split cutoffs must advance before evidence cutoff")
    splits: list[list[str]] = [[], [], []]
    identities = set()
    windows = []
    for identity, start, end in execution_windows:
        a, b = parse_aware_timestamp(start, "execution start"), parse_aware_timestamp(end, "execution end")
        if not identity or identity in identities or not a < b <= cutoff:
            raise ValueError("invalid, duplicate or future dataset execution")
        identities.add(identity)
        if a < train_stop < b or a < validation_stop < b:
            raise ValueError("execution crosses a dataset split boundary")
        windows.append((a, b, identity))
    for a, b, identity in sorted(windows):
        group = 0 if b <= train_stop else 1 if a >= train_stop and b <= validation_stop else 2
        splits[group].append(identity)
    result = DatasetManifest(dataset_id, source, license, evidence_cutoff,
        hashlib.sha256(content).hexdigest(), unit_boundaries, transformation_version,
        *(tuple(group) for group in splits), truth_class)
    result.validate()
    return result


def write_artifact(directory: Path, payload: dict) -> str:
    fingerprint = digest(payload)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (fingerprint + ".json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    try:
        with path.open("x", encoding="utf-8") as target:
            target.write(encoded)
    except FileExistsError:
        if read_artifact(directory, fingerprint) != payload:
            raise ValueError("immutable artifact collision")
    return fingerprint


def read_artifact(directory: Path, fingerprint: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ValueError("invalid artifact identity")
    payload = json.loads((directory / (fingerprint + ".json")).read_text(encoding="utf-8"))
    if digest(payload) != fingerprint:
        raise ValueError("artifact integrity check failed")
    return payload


def qualify_model_artifact(
    *,
    model_name: str,
    model_version: str,
    parameters: dict,
    dataset: DatasetManifest,
    metrics: dict[str, float],
    thresholds: dict[str, float],
    operating_range: dict,
    reviewer: str,
    approved_at: str,
) -> dict:
    dataset.validate()
    approved = parse_aware_timestamp(approved_at, "approval time")
    if approved < parse_aware_timestamp(dataset.evidence_cutoff, "evidence cutoff"):
        raise ValueError("approval precedes evidence")
    if not all(
        (model_name, model_version, parameters, operating_range, reviewer, metrics, thresholds)
    ):
        raise ValueError("model qualification metadata is incomplete")
    # JSON serialization prohibits nonfinite metrics and parameters.
    digest({"metrics": metrics, "thresholds": thresholds, "parameters": parameters})
    if set(metrics) != set(thresholds) or any(
        metrics[k] < 0 or thresholds[k] < 0 or metrics[k] > thresholds[k] for k in metrics
    ):
        raise ValueError("model has not passed every declared held-out threshold")
    return {
        "schema_version": "gridpulse-calibrated-model-artifact-v1",
        "model_name": model_name,
        "model_version": model_version,
        "parameters": parameters,
        "dataset": asdict(dataset),
        "metrics": metrics,
        "thresholds": thresholds,
        "operating_range": operating_range,
        "reviewer": reviewer,
        "approved_at": approved_at,
        "qualification_basis": "held_out_model_validation",
    }


def release_manifest(
    *,
    wheel: Path,
    engine_version: str,
    source_revision: str,
    dependency_lock: Path,
    calibration_fingerprints: tuple[str, ...] = (),
) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", source_revision) or not engine_version:
        raise ValueError("release requires an exact source revision and engine version")
    if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in calibration_fingerprints):
        raise ValueError("release calibration identities must be content hashes")
    return {
        "schema_version": "gridpulse-engine-release-v1",
        "engine_version": engine_version,
        "source_revision": source_revision,
        "wheel_sha256": sha256_file(wheel),
        "dependency_lock_sha256": sha256_file(dependency_lock),
        "calibration_fingerprints": list(calibration_fingerprints),
    }


def verify_release_manifest(
    manifest: dict, *, wheel: Path, dependency_lock: Path, source_revision: str, engine_version: str
) -> None:
    """Verify the bytes to be installed against the qualified release identity."""
    expected = release_manifest(
        wheel=wheel,
        engine_version=engine_version,
        source_revision=source_revision,
        dependency_lock=dependency_lock,
        calibration_fingerprints=tuple(manifest.get("calibration_fingerprints", ())),
    )
    if manifest != expected:
        raise ValueError("release artifact identity or content mismatch")


def load_qualified_model(
    directory: Path,
    fingerprint: str,
    *,
    release: dict,
    model_name: str,
    observed_at: str,
    operating_point: dict[str, float],
    require_measured: bool = True,
) -> dict:
    """Explicit, fail-closed promotion gate. Does not train or select an active model.

    The caller must first verify the wheel/lock release manifest. This additionally
    verifies approved calibration identity, held-out qualification and applicability.
    """
    from math import isfinite

    if release.get(
        "schema_version"
    ) != "gridpulse-engine-release-v1" or fingerprint not in release.get(
        "calibration_fingerprints", []
    ):
        raise ValueError("calibration is not approved by this engine release")
    artifact = read_artifact(directory, fingerprint)
    if (
        artifact.get("schema_version") != "gridpulse-calibrated-model-artifact-v1"
        or artifact.get("model_name") != model_name
    ):
        raise ValueError("model artifact identity mismatch")
    dataset = DatasetManifest(**artifact["dataset"])
    qualified = qualify_model_artifact(
        model_name=artifact["model_name"],
        model_version=artifact["model_version"],
        parameters=artifact["parameters"],
        dataset=dataset,
        metrics=artifact["metrics"],
        thresholds=artifact["thresholds"],
        operating_range=artifact["operating_range"],
        reviewer=artifact["reviewer"],
        approved_at=artifact["approved_at"],
    )
    if artifact != qualified:
        raise ValueError("model qualification record differs")
    if require_measured and dataset.truth_class != "measured":
        raise ValueError("site serving requires measured calibration evidence")
    if parse_aware_timestamp(observed_at, "observed_at") < parse_aware_timestamp(
        artifact["approved_at"], "approved_at"
    ):
        raise ValueError("calibration was not available at the observation time")
    ranges = artifact["operating_range"]
    if set(operating_point) != set(ranges):
        raise ValueError("every calibrated operating dimension is required")
    for name, value in operating_point.items():
        bounds = ranges[name]
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) != 2
            or not all(isfinite(x) for x in (*bounds, value))
            or not bounds[0] <= value <= bounds[1]
        ):
            raise ValueError("outside calibrated operating range")
    return artifact
