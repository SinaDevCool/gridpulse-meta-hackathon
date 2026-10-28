"""Robust GeoJSON matching for points and parcels with explicit ambiguity states."""

from __future__ import annotations

import math

from shapely.geometry import Point, shape
from shapely.ops import nearest_points

from .contracts import SiteLocation, TerritoryMatch, TerritorySnapshot


def _haversine_m(left: Point, right: Point) -> float:
    radius = 6_371_008.8
    lat1, lat2 = math.radians(left.y), math.radians(right.y)
    dlat = lat2 - lat1
    dlon = math.radians(right.x - left.x)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def validate_geojson_geometry(geometry: dict[str, object]) -> None:
    candidate = shape(geometry)
    if candidate.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("operator territory must be Polygon or MultiPolygon")
    if candidate.is_empty or not candidate.is_valid:
        raise ValueError("operator territory geometry is empty or invalid")


def parcel_intersection_shares(
    parcel_geometry: dict[str, object], territories: list[TerritorySnapshot]
) -> dict[str, float]:
    parcel = shape(parcel_geometry)
    if parcel.is_empty or not parcel.is_valid or parcel.area <= 0:
        raise ValueError("parcel geometry is empty or invalid")
    shares: dict[str, float] = {}
    for territory in territories:
        area = parcel.intersection(shape(territory.geometry)).area
        if area > 0:
            shares[territory.operator_id] = shares.get(territory.operator_id, 0) + area / parcel.area
    return {key: round(value, 8) for key, value in shares.items()}


def match_site_to_territories(
    location: SiteLocation,
    territories: list[TerritorySnapshot],
    *,
    boundary_review_m: float = 500,
) -> TerritoryMatch:
    location.validate()
    if boundary_review_m < 0:
        raise ValueError("boundary review distance must be non-negative")
    point = Point(location.longitude, location.latitude)
    covered: list[tuple[TerritorySnapshot, bool, float]] = []
    evidence = []
    for territory in territories:
        territory.validate()
        validate_geojson_geometry(territory.geometry)
        polygon = shape(territory.geometry)
        if polygon.covers(point):
            touching = polygon.boundary.covers(point)
            nearest = nearest_points(point, polygon.boundary)[1]
            covered.append((territory, touching, _haversine_m(point, nearest)))
            evidence.append(territory.territory_id)
    if location.parcel_geometry is not None:
        shares = parcel_intersection_shares(location.parcel_geometry, territories)
        material = [operator for operator, share in shares.items() if share > 0.001]
        if len(material) > 1:
            return TerritoryMatch(location.site_id, None, None, "ambiguous", "parcel_intersection",
                                  0, None, tuple(sorted(material)), True, tuple(evidence))
    if not covered:
        return TerritoryMatch(location.site_id, None, None, "uncovered", "geojson_point", 0, None,
                              (), True, tuple(evidence))
    operators = sorted({item[0].operator_id for item in covered})
    if len(operators) > 1:
        return TerritoryMatch(location.site_id, None, None, "overlapping", "geojson_point", 0,
                              min(item[2] for item in covered), tuple(operators), True, tuple(evidence))
    territory, touching, distance = covered[0]
    near = touching or distance <= boundary_review_m
    status = "boundary" if near else "matched"
    accuracy = location.coordinate_accuracy_m or 0
    confidence = 0.5 if touching else max(0.55, min(1.0, distance / max(boundary_review_m, 1)))
    if not touching and accuracy >= distance:
        status, confidence, near = "ambiguous", min(confidence, 0.4), True
    return TerritoryMatch(
        location.site_id, territory.territory_id if status != "ambiguous" else None,
        territory.operator_id if status != "ambiguous" else None, status, "geojson_point",
        round(confidence, 4), round(distance, 2), (), near, tuple(evidence),
    )
