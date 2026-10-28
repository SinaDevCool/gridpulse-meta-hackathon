"""Deterministic operator identity matching with explicit ambiguity quarantine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .identity import normalize_name


@dataclass(frozen=True)
class OperatorIdentity:
    canonical_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    control_area: str
    regions: tuple[str, ...]
    match_resolution: str


@dataclass(frozen=True)
class OperatorMatch:
    raw_name: str
    canonical_id: str | None
    method: str
    confidence: float
    review_required: bool


def load_operator_identities(path: Path) -> list[OperatorIdentity]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    identities = [
        OperatorIdentity(
            item["canonical_id"],
            item["canonical_name"],
            tuple(item["aliases"]),
            item["control_area"],
            tuple(item["regions"]),
            item["match_resolution"],
        )
        for item in payload.get("operators", [])
    ]
    aliases: dict[str, str] = {}
    for identity in identities:
        for value in (identity.canonical_name, *identity.aliases):
            key = normalize_name(value)
            if key in aliases and aliases[key] != identity.canonical_id:
                raise ValueError(f"operator alias collision: {value}")
            aliases[key] = identity.canonical_id
    return identities


def match_operator(raw_name: str, identities: list[OperatorIdentity]) -> OperatorMatch:
    key = normalize_name(raw_name)
    exact = []
    for identity in identities:
        names = (identity.canonical_name, *identity.aliases)
        if key in {normalize_name(value) for value in names}:
            exact.append(identity.canonical_id)
    if len(exact) == 1:
        return OperatorMatch(raw_name, exact[0], "exact_published_alias", 1.0, False)
    if len(exact) > 1:
        return OperatorMatch(raw_name, None, "alias_collision", 0.0, True)
    return OperatorMatch(raw_name, None, "unmatched", 0.0, True)
