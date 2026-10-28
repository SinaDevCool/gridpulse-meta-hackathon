"""Versioned territory-source normalization and as-known-at-time release selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from capacity_backtest.domain.base import parse_aware_timestamp
from grid_data.open_sources import parse_vnbdigital_operator_csv

from .contracts import TerritorySnapshot


def parse_vnbdigital_crosswalk(content: bytes) -> list[dict[str, Any]]:
    """Reuse the governed parser and mark non-spatial rows as review-only."""
    return [
        {**row, "spatial_resolution": "region_crosswalk", "review_required": True}
        for row in parse_vnbdigital_operator_csv(content)
    ]


def ingest_territory_geojson(
    content: bytes,
    output: Path,
    *,
    source_id: str,
    source_url: str,
    licence: str,
    retrieved_at: str,
) -> list[TerritorySnapshot]:
    if not licence.strip():
        raise ValueError("territory reuse licence is required")
    payload = json.loads(content)
    if payload.get("type") != "FeatureCollection":
        raise ValueError("territory source must be a GeoJSON FeatureCollection")
    artifact_hash = hashlib.sha256(content).hexdigest()
    snapshots: list[TerritorySnapshot] = []
    seen: set[str] = set()
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        territory_id = str(properties.get("territory_id", "")).strip()
        if not territory_id or territory_id in seen:
            raise ValueError("territory IDs must be present and unique")
        seen.add(territory_id)
        snapshot = TerritorySnapshot(
            territory_id=territory_id,
            operator_id=str(properties.get("operator_id", "")),
            operator_name=str(properties.get("operator_name", "")),
            network_level=str(properties.get("network_level", "distribution")),
            geometry=feature.get("geometry") or {},
            valid_from=str(properties.get("valid_from", "")),
            valid_to=properties.get("valid_to"),
            published_at=str(properties.get("published_at", "")),
            retrieved_at=retrieved_at,
            source_id=source_id,
            source_url=source_url,
            artifact_hash=artifact_hash,
            licence=licence,
            evidence_class=str(properties.get("evidence_class", "official_public")),
        )
        snapshot.validate()
        snapshots.append(snapshot)
    if not snapshots:
        raise ValueError("territory release contains no features")
    normalized = {
        "schema_version": "gridpulse-territory-release-v1",
        "source_id": source_id,
        "source_url": source_url,
        "licence": licence,
        "retrieved_at": retrieved_at,
        "artifact_hash": artifact_hash,
        "snapshots": [asdict(item) for item in snapshots],
    }
    release_bytes = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    normalized["release_sha256"] = hashlib.sha256(release_bytes).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return snapshots


def load_territory_release(path: Path) -> list[TerritorySnapshot]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "gridpulse-territory-release-v1":
        raise ValueError("unsupported territory release schema")
    expected = payload.pop("release_sha256", None)
    release_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if expected != hashlib.sha256(release_bytes).hexdigest():
        raise ValueError("territory release hash mismatch")
    snapshots = [TerritorySnapshot(**row) for row in payload.get("snapshots", [])]
    for item in snapshots:
        item.validate()
        if item.artifact_hash != payload.get("artifact_hash"):
            raise ValueError("territory release artifact hash mismatch")
    return snapshots


def select_territories_as_known(
    snapshots: list[TerritorySnapshot], *, decision_time: str, evidence_cutoff: str
) -> list[TerritorySnapshot]:
    decision = parse_aware_timestamp(decision_time, "decision_time")
    cutoff = parse_aware_timestamp(evidence_cutoff, "evidence_cutoff")
    if cutoff > decision:
        raise ValueError("evidence cutoff cannot follow decision time")
    selected = []
    for snapshot in snapshots:
        snapshot.validate()
        start = parse_aware_timestamp(snapshot.valid_from, "valid_from")
        end = parse_aware_timestamp(snapshot.valid_to, "valid_to") if snapshot.valid_to else None
        published = parse_aware_timestamp(snapshot.published_at, "published_at")
        retrieved = parse_aware_timestamp(snapshot.retrieved_at, "retrieved_at")
        if start <= decision and (end is None or decision < end) and published <= cutoff and retrieved <= cutoff:
            selected.append(snapshot)
    return selected


def verify_no_active_overlaps_by_identity(snapshots: list[TerritorySnapshot]) -> None:
    """Reject duplicate active definitions before geometric overlap checks in T3."""
    keys: set[tuple[str, datetime]] = set()
    for snapshot in snapshots:
        key = (snapshot.territory_id, parse_aware_timestamp(snapshot.valid_from, "valid_from"))
        if key in keys:
            raise ValueError("duplicate territory identity and validity start")
        keys.add(key)
