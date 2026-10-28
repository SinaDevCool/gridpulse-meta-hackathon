from capacity_backtest.backtest import BenchmarkRecord
from capacity_backtest.flex_study import run_synthetic_flexibility_study


def record(security, capacity):
    return BenchmarkRecord(
        "family",
        "node",
        "Node",
        "winter",
        security,
        capacity,
        "line",
        110,
        2,
        1,
        2,
        0,
        False,
        "memory",
        1,
        2,
        0.5,
        None,
    )


def test_flex_study_has_all_load_scenarios_and_stays_synthetic():
    result = run_synthetic_flexibility_study([record("n_0", 120), record("n_1", 80)])
    assert result["capacity_claim"] is False
    assert result["classification"] == "synthetic_benchmark"
    assert [row["site_load_mw"] for row in result["results"]] == [10, 25, 50, 100, 200]
    assert all("trace" not in row for row in result["results"])
