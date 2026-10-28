"""MaStR-style network-operator registry ingestion and identifier-first reconciliation."""

from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from capacity_backtest.domain.base import parse_aware_timestamp
from capacity_backtest.identity import normalize_name

from .contracts import OperatorRegistryEntry


@dataclass(frozen=True)
class RegistryRelease:
    source_id: str
    artifact_hash: str
    published_at: str
    retrieved_at: str
    entries: tuple[OperatorRegistryEntry, ...]

    def validate(self) -> None:
        published = parse_aware_timestamp(self.published_at, "published_at")
        retrieved = parse_aware_timestamp(self.retrieved_at, "retrieved_at")
        if published > retrieved:
            raise ValueError("registry publication cannot follow retrieval")
        if len(self.artifact_hash) != 64 or not self.entries:
            raise ValueError("registry release requires a SHA-256 artifact and entries")
        for entry in self.entries:
            entry.validate()


@dataclass(frozen=True)
class RegistryMatch:
    operator_id: str | None
    method: str
    confidence: float
    review_required: bool


def _fields(element: ET.Element) -> dict[str, str]:
    return {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in element.iter()}


def parse_mastr_operator_registry(
    content: bytes, *, source_id: str, published_at: str, retrieved_at: str
) -> RegistryRelease:
    digest = hashlib.sha256(content).hexdigest()
    entries = []
    for _, element in ET.iterparse(io.BytesIO(content), events=("end",)):
        fields = _fields(element)
        role = fields.get("Marktfunktion") or fields.get("Marktrolle") or fields.get("Rolle")
        legal_name = fields.get("Firmenname") or fields.get("Name") or fields.get("MarktakteurName")
        mastr = fields.get("MastrNummer") or fields.get("MarktakteurMastrNummer")
        if role and "stromnetzbetreiber" in normalize_name(role) and legal_name and mastr:
            entries.append(OperatorRegistryEntry(
                operator_id=normalize_name(mastr).replace(" ", "-"), legal_name=legal_name,
                market_roles=("Stromnetzbetreiber",), status=fields.get("Status") or "active",
                source_id=source_id, artifact_hash=digest, mastr_number=mastr,
                bdew_code=fields.get("BdewCode") or None,
                aliases=tuple(filter(None, (fields.get("Kurzname"),))),
            ))
            element.clear()
    deduplicated = {entry.mastr_number: entry for entry in entries}
    release = RegistryRelease(source_id, digest, published_at, retrieved_at, tuple(deduplicated.values()))
    release.validate()
    return release


def select_registry_as_known(release: RegistryRelease, evidence_cutoff: str) -> tuple[OperatorRegistryEntry, ...]:
    release.validate()
    cutoff = parse_aware_timestamp(evidence_cutoff, "evidence_cutoff")
    if parse_aware_timestamp(release.published_at, "published_at") > cutoff or parse_aware_timestamp(
        release.retrieved_at, "retrieved_at"
    ) > cutoff:
        return ()
    return release.entries


def reconcile_operator(
    entries: tuple[OperatorRegistryEntry, ...] | list[OperatorRegistryEntry], *,
    mastr_number: str | None = None, bdew_code: str | None = None,
    canonical_id: str | None = None, name: str | None = None,
) -> RegistryMatch:
    if mastr_number:
        matches = [row for row in entries if row.mastr_number == mastr_number]
        return _unique(matches, "mastr_number", 1.0)
    if bdew_code:
        matches = [row for row in entries if row.bdew_code == bdew_code]
        return _unique(matches, "bdew_code", 1.0)
    if canonical_id:
        matches = [row for row in entries if row.operator_id == canonical_id]
        if matches:
            return _unique(matches, "canonical_id", 0.98)
    if name:
        key = normalize_name(name)
        matches = [row for row in entries if key in {normalize_name(row.legal_name), *map(normalize_name, row.aliases)}]
        return _unique(matches, "reviewed_legal_name", 0.9)
    return RegistryMatch(None, "unmatched", 0, True)


def _unique(matches: list[OperatorRegistryEntry], method: str, confidence: float) -> RegistryMatch:
    if len(matches) == 1:
        return RegistryMatch(matches[0].operator_id, method, confidence, False)
    return RegistryMatch(None, "ambiguous" if matches else "unmatched", 0, True)
