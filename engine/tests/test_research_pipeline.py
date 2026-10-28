from datetime import datetime, timedelta, timezone

import pytest

from capacity_backtest.graph_export import export_neo4j_csv
from capacity_backtest.models import MeanBaseline, TabPFNRegressorAdapter, regression_metrics
from capacity_backtest.regions import load_regions, point_in_polygon
from capacity_backtest.scenarios import Battery, annual_summary, apply_battery
from capacity_backtest.timeseries import (
    HourlyObservation,
    build_lagged_rows,
    chronological_split,
    validate_hourly,
)
from grid_data.berlin_synthetic_capacity import build_berlin_synthetic_model


def test_region_registry_and_containment(tmp_path):
    config = tmp_path / "regions.yaml"
    config.write_text("regions:\n  - {id: DE-X, name: Test, kind: state, components: [Test]}\n")
    assert load_regions(config)[0].id == "DE-X"
    square = [(0, 0), (2, 0), (2, 2), (0, 2)]
    assert point_in_polygon(1, 1, square)
    assert not point_in_polygon(3, 1, square)


def test_lags_use_past_only_and_split_is_chronological():
    start = datetime(2023, 12, 31, 23, tzinfo=timezone.utc)
    observations = [HourlyObservation(start + timedelta(hours=i), "DE-BE", float(i)) for i in range(3)]
    rows = build_lagged_rows(observations, (1,))
    assert rows[0]["load_lag_1h"] is None
    assert rows[1]["load_lag_1h"] == 0
    train, test = chronological_split(rows, 2024)
    assert len(train) == 1 and len(test) == 2


def test_hourly_validation_reports_gaps_and_rejects_duplicates():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert validate_hourly([HourlyObservation(start, "x", 1), HourlyObservation(start + timedelta(hours=2), "x", 2)])
    with pytest.raises(ValueError, match="duplicate"):
        validate_hourly([HourlyObservation(start, "x", 1), HourlyObservation(start, "x", 2)])


def test_baseline_metrics_and_tabpfn_fail_closed(monkeypatch):
    result = MeanBaseline().fit_predict([[1]], [10, 20], [[2], [3]])
    assert result.predictions == [15, 15]
    assert regression_metrics([10, 20], result.predictions)["mae"] == 5
    monkeypatch.delenv("TABPFN_TOKEN", raising=False)
    assert TabPFNRegressorAdapter().fit_predict([[1]], [1], [[2]]).status == "unavailable"


def test_battery_obeys_power_energy_and_annual_contract():
    result = apply_battery([120, 120], 100, Battery(10, 15, 1, 15))
    assert result["net_load_mw"] == [110, 115]
    assert result["remaining_soc_mwh"] == 0
    with pytest.raises(ValueError, match="8,760"):
        annual_summary([1], 1)
    assert annual_summary([100] * 8760, 90)["hours_above_threshold"] == 8760


def test_neo4j_export_is_portable_and_not_a_capacity_claim(tmp_path):
    result = export_neo4j_csv(build_berlin_synthetic_model(), tmp_path)
    assert result["nodes"] > 0 and not result["capacity_claim"]
    assert (tmp_path / "nodes.csv").is_file()
