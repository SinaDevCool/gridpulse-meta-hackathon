"""Versioned study-region definitions and conservative point containment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    kind: str
    components: tuple[str, ...]


def load_regions(path: Path) -> list[Region]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    regions = [Region(**{**item, "components": tuple(item["components"])}) for item in payload.get("regions", [])]
    if not regions:
        raise ValueError("region registry is empty")
    if len({region.id for region in regions}) != len(regions):
        raise ValueError("duplicate region id")
    return regions


def point_in_polygon(longitude: float, latitude: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting containment; boundary datasets must retain their source/version separately."""
    if len(polygon) < 3:
        raise ValueError("polygon requires at least three points")
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        crosses = (y1 > latitude) != (y2 > latitude)
        if crosses:
            intersection = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < intersection:
                inside = not inside
        previous = current
    return inside
