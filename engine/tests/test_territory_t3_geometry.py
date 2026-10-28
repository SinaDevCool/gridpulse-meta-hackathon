from dataclasses import replace

import pytest

from capacity_backtest.territory.contracts import SiteLocation, TerritorySnapshot
from capacity_backtest.territory.geometry import (
    match_site_to_territories,
    validate_geojson_geometry,
)


def territory(operator="snb", geometry=None):
    return TerritorySnapshot("t-"+operator, operator, operator, "distribution", geometry or {
        "type":"Polygon", "coordinates":[[[13,52],[14,52],[14,53],[13,53],[13,52]],
                                              [[13.4,52.4],[13.6,52.4],[13.6,52.6],[13.4,52.6],[13.4,52.4]]]},
        "2024-01-01T00:00:00Z", None, "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z",
        "source", "https://example.test", "a"*64, "CC BY", "official_public")


def location(lon=13.2, lat=52.2, accuracy=10, parcel=None):
    return SiteLocation("site", lat, lon, "address_rooftop", "source", "2025-01-01T00:00:00Z",
                        coordinate_accuracy_m=accuracy, parcel_geometry=parcel)


def test_polygon_hole_boundary_and_overlap_are_not_silently_matched() -> None:
    assert match_site_to_territories(location(), [territory()], boundary_review_m=100).match_status == "matched"
    assert match_site_to_territories(location(13.5,52.5), [territory()]).match_status == "uncovered"
    assert match_site_to_territories(location(13,52.5), [territory()]).match_status == "boundary"
    assert match_site_to_territories(location(), [territory(), territory("edis")]).match_status == "overlapping"


def test_multipolygon_and_cross_operator_parcel() -> None:
    multi={"type":"MultiPolygon","coordinates":[[[[13,52],[14,52],[14,53],[13,53],[13,52]]]]}
    assert match_site_to_territories(location(), [territory(geometry=multi)]).match_status == "matched"
    parcel={"type":"Polygon","coordinates":[[[13.9,52.1],[14.1,52.1],[14.1,52.2],[13.9,52.2],[13.9,52.1]]]}
    other={"type":"Polygon","coordinates":[[[14,52],[15,52],[15,53],[14,53],[14,52]]]}
    result=match_site_to_territories(location(parcel=parcel), [territory(),territory("edis",other)])
    assert result.match_status == "ambiguous"


def test_invalid_geometry_rejected() -> None:
    with pytest.raises(ValueError, match="invalid"):
        validate_geojson_geometry({"type":"Polygon","coordinates":[[[0,0],[1,1],[1,0],[0,1],[0,0]]]})
    assert match_site_to_territories(replace(location(), coordinate_accuracy_m=100000), [territory()]).match_status == "ambiguous"
