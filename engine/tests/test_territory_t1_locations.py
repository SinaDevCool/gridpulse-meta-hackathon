import json

import pytest

from capacity_backtest.territory.locations import (
    capture_location,
    replay_location,
    validate_location_for_territory,
)


def test_location_capture_replays_and_detects_tampering(tmp_path) -> None:
    path = tmp_path / "site.json"
    capture_location(
        {"site_id": "berlin-1", "address": "Berlin", "coordinate_accuracy_m": 10},
        b'[{"lat":"52.5","lon":"13.4"}]', path, provider="test", source_url="https://example.test",
        retrieved_at="2025-01-01T00:00:00Z",
    )
    assert replay_location(path).site_id == "berlin-1"
    payload = json.loads(path.read_text())
    payload["location"]["latitude"] = 53
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_location(path)


def test_location_uncertainty_and_postcode_centroid_require_review(tmp_path) -> None:
    path = tmp_path / "site.json"
    capture_location(
        {"site_id": "boundary", "coordinate_method": "postcode_centroid", "coordinate_accuracy_m": 5000},
        b'{"latitude":52.5,"longitude":13.4}', path, provider="test", source_url="https://example.test",
        retrieved_at="2025-01-01T00:00:00Z",
    )
    reasons = validate_location_for_territory(replay_location(path), boundary_distance_m=1000)
    assert len(reasons) == 2
