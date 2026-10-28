import json
from pathlib import Path

import pytest

from capacity_backtest.contracts import TruthClass
from capacity_backtest.network_contracts import NETWORK_SCHEMA_VERSION, load_network_package


def payload() -> dict:
    return {
        "schema_version": NETWORK_SCHEMA_VERSION,
        "model_id": "mock-grid",
        "model_version": "1",
        "truth_class": TruthClass.SYNTHETIC_BENCHMARK.value,
        "effective_at": "2026-01-01T00:00:00+00:00",
        "buses": [{"id": "a"}, {"id": "b"}],
        "branches": [{"id": "line", "from_bus": "a", "to_bus": "b"}],
        "transformers": [],
        "switches": [],
        "operational_limits": [{"asset_id": "line", "value": 100, "unit": "A"}],
        "provenance": {
            "source_id": "simbench",
            "source_url": "https://simbench.de",
            "retrieved_at": "2026-01-01T00:00:00+00:00",
            "snapshot_hash": "a" * 64,
            "licence": "reference terms",
            "geographic_resolution": "synthetic_reference_network",
        },
        "operator_validated": False,
    }


def test_network_package_is_fingerprinted_and_never_a_capacity_claim(tmp_path: Path) -> None:
    path = tmp_path / "network.json"
    path.write_text(json.dumps(payload()))
    package = load_network_package(path)
    assert len(package.fingerprint()) == 64
    assert package.as_dict()["available_capacity_mw"] is None


def test_network_package_fails_on_unknown_connectivity(tmp_path: Path) -> None:
    invalid = payload()
    invalid["branches"][0]["to_bus"] = "missing"
    path = tmp_path / "network.json"
    path.write_text(json.dumps(invalid))
    with pytest.raises(ValueError, match="unknown bus"):
        load_network_package(path)
