"""Canonical data-center operator enquiry and evidence package composition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

from capacity_backtest.storage import atomic_write


@dataclass(frozen=True)
class EvidencePackage:
    destination: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    package_fingerprint: str
    capacity_claim: bool = False
    automatic_live_dispatch_authorized: bool = False


@dataclass(frozen=True)
class EvidencePackageContent:
    payload: dict[str, Any]
    json_text: str
    markdown_text: str
    manifest: dict[str, Any]
    package_fingerprint: str


def _value(item: Any) -> Any:
    if is_dataclass(item) and not isinstance(item, type):
        return _value(asdict(cast(Any, item)))
    if isinstance(item, Enum):
        return item.value
    if isinstance(item, Mapping):
        return {str(key): _value(value) for key, value in item.items()}
    if isinstance(item, (tuple, list)):
        return [_value(value) for value in item]
    if isinstance(item, Path):
        return str(item)
    return item


def compose_data_center_enquiry_package(
    *,
    package_id: str,
    artifacts: Mapping[str, object],
    blockers: tuple[str, ...] = (),
    assumption_ids: tuple[str, ...] = (),
) -> EvidencePackageContent:
    if not package_id or not artifacts:
        raise ValueError("evidence package identity and artifacts are required")
    payload = {
        "schema_version": "gridpulse-data-center-enquiry-v1",
        "package_id": package_id,
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "blockers": list(blockers),
        "assumption_ids": list(assumption_ids),
        "artifacts": {key: _value(value) for key, value in sorted(artifacts.items())},
    }
    json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    encoded = json_text.encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    markdown_text = "\n".join([
        f"# GridPulse operator enquiry: {package_id}", "",
        "- Capacity claim: **No**", "- Automatic live dispatch authorized: **No**",
        f"- Package fingerprint: `{fingerprint}`", "",
        "## Included canonical artifacts", "",
        *[f"- `{name}`" for name in sorted(artifacts)], "",
        "## Blockers", "",
        *([f"- {item}" for item in blockers] or ["- None recorded"]), "",
    ])
    markdown = markdown_text.encode()
    manifest = {
        "schema_version": "gridpulse-data-center-enquiry-manifest-v1",
        "package_id": package_id,
        "package_fingerprint": fingerprint,
        "artifact_sha256": {
            "operator-enquiry.json": hashlib.sha256(encoded).hexdigest(),
            "operator-enquiry.md": hashlib.sha256(markdown).hexdigest(),
        },
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
    }
    return EvidencePackageContent(payload, json_text, markdown_text, manifest, fingerprint)


def build_data_center_enquiry_package(
    destination: Path,
    *,
    package_id: str,
    artifacts: Mapping[str, object],
    blockers: tuple[str, ...] = (),
    assumption_ids: tuple[str, ...] = (),
) -> EvidencePackage:
    content = compose_data_center_enquiry_package(
        package_id=package_id, artifacts=artifacts, blockers=blockers, assumption_ids=assumption_ids
    )
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "operator-enquiry.json"
    markdown_path = destination / "operator-enquiry.md"
    manifest_path = destination / "manifest.json"
    atomic_write(json_path, content.json_text.encode())
    atomic_write(markdown_path, content.markdown_text.encode())
    atomic_write(manifest_path, (json.dumps(content.manifest, indent=2, sort_keys=True) + "\n").encode())
    return EvidencePackage(destination, json_path, markdown_path, manifest_path, content.package_fingerprint)
