import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from capacity_backtest.backtest import BenchmarkRecord
from capacity_backtest.queue_backtest import build_queue_feature_rows
from capacity_backtest.synthetic_operator import (
    SyntheticOperatorConfig,
    build_synthetic_operator_package,
    verify_synthetic_operator_package,
)


def record(network: str, node: str, security: str, capacity: float) -> BenchmarkRecord:
    return BenchmarkRecord(
        network,
        node,
        node,
        "annual_median",
        security,
        capacity,
        "line_thermal_loading",
        110,
        2,
        5,
        2,
        0,
        False,
        "deterministic_in_memory",
        5,
        30,
        0.83,
        None,
    )


def read_rows(root: Path, table: dict) -> list[dict]:
    with gzip.open(root / table["path"], "rt", encoding="utf-8") as source:
        return [json.loads(line) for line in source]


def test_operator_package_links_chronological_mock_tables_and_stays_synthetic(
    tmp_path: Path,
) -> None:
    records = [
        record("berlin-geographic-synthetic-110kv-family-1", "osm-way-30132758", "n_0", 120),
        record("berlin-geographic-synthetic-110kv-family-1", "osm-way-30132758", "n_1", 60),
        record("berlin-geographic-synthetic-110kv-family-2", "osm-way-46615737", "n_0", 90),
        record("berlin-geographic-synthetic-110kv-family-2", "osm-way-46615737", "n_1", 40),
    ]
    data_root, work_root = tmp_path / "cloud", tmp_path / "work"
    config = SyntheticOperatorConfig(
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        hours=24,
        requests_per_node=3,
    )
    first = build_synthetic_operator_package(records, data_root, work_root, config)
    second = build_synthetic_operator_package(records, data_root, work_root, config)
    assert first["run_id"] == second["run_id"]
    assert first["truth_class"] == "synthetic_benchmark"
    assert first["available_capacity_mw"] is None
    verification = verify_synthetic_operator_package(Path(first["manifest_path"]), data_root)
    assert verification["status"] == "verified"
    assert verification["rows"] == sum(table["rows"] for table in first["tables"].values())
    assert first["tables"]["hourly_operating_states"]["rows"] == 48
    requests = read_rows(data_root, first["tables"]["queue_requests"])
    outcomes = read_rows(data_root, first["tables"]["connection_study_outcomes"])
    outages = read_rows(data_root, first["tables"]["outages"])
    assert {row["request_id"] for row in requests} == {row["request_id"] for row in outcomes}
    assert all(row["capacity_claim"] is False for row in outcomes)
    for request, outcome in zip(requests, outcomes):
        assert datetime.fromisoformat(request["submitted_at"]) < datetime.fromisoformat(
            outcome["decision_at"]
        )
    assert all(row["known_outage_ids_at_decision"] for row in outcomes)
    assert {row["revision"] for row in outages} == {1, 2}
    features = build_queue_feature_rows(Path(first["manifest_path"]), data_root)
    assert all(row["evidence_cutoff"] == row["submitted_at"] for row in features)
    assert all("decision_at" not in row for row in features)


def test_operator_package_requires_paired_n0_n1_records(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="paired"):
        build_synthetic_operator_package(
            [
                record(
                    "berlin-geographic-synthetic-110kv-family-1",
                    "osm-way-30132758",
                    "n_0",
                    100,
                )
            ],
            tmp_path / "cloud",
            tmp_path / "work",
            SyntheticOperatorConfig(hours=1),
        )
