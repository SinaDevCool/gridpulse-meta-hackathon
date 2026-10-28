"""Reviewable node matching; proposals are never silently accepted."""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

MATCH_STATUSES = {"accepted", "probable", "ambiguous", "rejected", "unmatched"}


@dataclass(frozen=True)
class Node:
    node_id: str
    name: str
    operator: str
    voltage_kv: float | None
    latitude: float | None
    longitude: float | None
    source_reference: str


@dataclass(frozen=True)
class NodeMatch:
    official_node_id: str
    candidate_node_id: str | None
    status: str
    confidence: float
    name_score: float
    distance_km: float | None
    voltage_compatible: bool | None
    operator_compatible: bool | None
    reviewer_note: str

    def __post_init__(self) -> None:
        if self.status not in MATCH_STATUSES:
            raise ValueError(f"invalid match status: {self.status}")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_name(value: str) -> str:
    value = value.replace("ß", "ss")
    value = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def haversine_km(a: Node, b: Node) -> float | None:
    if None in {a.latitude, a.longitude, b.latitude, b.longitude}:
        return None
    radius = 6371.0088
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def propose_match(official: Node, candidate: Node) -> NodeMatch:
    official_tokens = set(normalize_name(official.name).split())
    candidate_tokens = set(normalize_name(candidate.name).split())
    union = official_tokens | candidate_tokens
    name_score = len(official_tokens & candidate_tokens) / len(union) if union else 0.0
    distance = haversine_km(official, candidate)
    voltage = (
        None
        if official.voltage_kv is None or candidate.voltage_kv is None
        else abs(official.voltage_kv - candidate.voltage_kv) < 0.1
    )
    operator = normalize_name(official.operator) in normalize_name(
        candidate.operator
    ) or normalize_name(candidate.operator) in normalize_name(official.operator)
    distance_score = 0.0 if distance is None else max(0.0, 1 - distance / 5)
    confidence = (
        0.55 * name_score
        + 0.25 * distance_score
        + 0.1 * float(voltage is True)
        + 0.1 * float(operator)
    )
    status = "probable" if confidence >= 0.75 else "ambiguous" if confidence >= 0.4 else "unmatched"
    return NodeMatch(
        official.node_id,
        candidate.node_id if status != "unmatched" else None,
        status,
        round(confidence, 4),
        round(name_score, 4),
        None if distance is None else round(distance, 3),
        voltage,
        operator,
        "Automated proposal; explicit review is required before acceptance.",
    )


def identity_review_queue(matches: list[NodeMatch]) -> list[dict[str, object]]:
    """Return ambiguous, low-confidence, or colliding proposals for manual review."""
    candidate_counts: dict[str, int] = {}
    for match in matches:
        if match.candidate_node_id:
            candidate_counts[match.candidate_node_id] = (
                candidate_counts.get(match.candidate_node_id, 0) + 1
            )
    queue = []
    for match in matches:
        collision = bool(match.candidate_node_id and candidate_counts[match.candidate_node_id] > 1)
        if match.status != "accepted" or match.confidence < 0.9 or collision:
            queue.append({**match.as_dict(), "collision": collision})
    return queue


def load_official_nodes(path: Path) -> list[Node]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            Node(
                row["node_id"],
                row["official_name"],
                row["operator"],
                float(row["voltage_kv"]) if row["voltage_kv"] else None,
                float(row["latitude"]) if row["latitude"] else None,
                float(row["longitude"]) if row["longitude"] else None,
                row["official_source_reference"],
            )
            for row in rows
        ]
