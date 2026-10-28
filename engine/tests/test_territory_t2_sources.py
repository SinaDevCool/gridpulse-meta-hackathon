import json

import pytest

from capacity_backtest.territory.sources import (
    ingest_territory_geojson,
    load_territory_release,
    parse_vnbdigital_crosswalk,
    select_territories_as_known,
)


def release(published="2024-01-01T00:00:00Z") -> bytes:
    return json.dumps({"type":"FeatureCollection","features":[{"type":"Feature","properties":{
        "territory_id":"berlin","operator_id":"snb","operator_name":"Stromnetz Berlin GmbH",
        "network_level":"distribution","valid_from":"2024-01-01T00:00:00Z",
        "published_at":published,"evidence_class":"official_public"},"geometry":{
        "type":"Polygon","coordinates":[[[13,52],[14,52],[14,53],[13,53],[13,52]]]}}]}).encode()


def test_versioned_release_blocks_future_knowledge(tmp_path) -> None:
    path = tmp_path / "release.json"
    rows = ingest_territory_geojson(release(), path, source_id="official",
        source_url="https://example.test/territory", licence="CC BY", retrieved_at="2024-02-01T00:00:00Z")
    assert select_territories_as_known(rows, decision_time="2024-03-01T00:00:00Z",
        evidence_cutoff="2024-02-01T00:00:00Z")
    assert not select_territories_as_known(rows, decision_time="2024-01-15T00:00:00Z",
        evidence_cutoff="2024-01-15T00:00:00Z")
    assert load_territory_release(path)[0].territory_id == "berlin"
    payload = json.loads(path.read_text())
    payload["snapshots"][0]["operator_id"] = "tampered"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="release hash mismatch"):
        load_territory_release(path)


def test_ingestion_rejects_missing_licence_and_vnb_crosswalk_is_review_only(tmp_path) -> None:
    with pytest.raises(ValueError, match="licence"):
        ingest_territory_geojson(release(), tmp_path / "x", source_id="x",
            source_url="https://example.test", licence="", retrieved_at="2025-01-01T00:00:00Z")
    rows = parse_vnbdigital_crosswalk(
        b"operator_name;region_code;source_url\nStromnetz Berlin;DE-BE;https://vnbdigital.de\n"
    )
    assert rows[0]["review_required"] and not rows[0]["capacity_claim"]
