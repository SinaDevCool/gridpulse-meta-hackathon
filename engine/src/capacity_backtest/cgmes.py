"""Fail-closed inventory gate for operator-supplied CGMES packages."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

REQUIRED_PROFILES = {"EQ", "SSH", "TP", "SV"}


@dataclass(frozen=True)
class CgmesInspection:
    sha256: str
    members: tuple[str, ...]
    profiles: tuple[str, ...]
    status: str
    truth_class: str = "operator_model_unvalidated"
    capacity_claim: bool = False


def inspect_cgmes_package(path: Path) -> CgmesInspection:
    """Check package integrity/profile presence; do not claim semantic model validation."""
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if not zipfile.is_zipfile(path):
        raise ValueError("CGMES package must be a ZIP archive")
    with zipfile.ZipFile(path) as archive:
        members = tuple(sorted(name for name in archive.namelist() if not name.endswith("/")))
        if not members:
            raise ValueError("CGMES package is empty")
        bad = archive.testzip()
        if bad:
            raise ValueError(f"CGMES package contains a corrupt member: {bad}")
        profiles = set()
        for name in members:
            upper = Path(name).stem.upper().replace("-", "_")
            for profile in REQUIRED_PROFILES:
                if profile in upper.split("_"):
                    profiles.add(profile)
        missing = REQUIRED_PROFILES - profiles
        if missing:
            raise ValueError(f"CGMES package is missing profiles: {sorted(missing)}")
        if any(not name.lower().endswith((".xml", ".rdf")) for name in members):
            raise ValueError("CGMES ZIP contains an unsupported non-XML/RDF member")
    return CgmesInspection(
        digest,
        members,
        tuple(sorted(profiles)),
        "profile_inventory_validated_semantics_unvalidated",
    )
