from datetime import datetime, timedelta, timezone

from capacity_backtest.validation import (
    annual_stress_scenarios,
    data_centre_flexibility_scenarios,
    rolling_origin_ridge,
    rolling_stress_classifier,
)


def test_annual_scenarios_are_not_capacity_claims():
    results = annual_stress_scenarios([100.0] * 8760)
    assert all(not row["capacity_claim"] for row in results)
    assert next(row for row in results if row["scenario"] == "plus_100_mw_site")["peak_mw"] == 200


def test_rolling_origin_uses_only_prior_years():
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    rows = []
    for hour in range(24 * 365 * 2):
        timestamp = start + timedelta(hours=hour)
        rows.append({"timestamp": timestamp.isoformat(), "x": float(hour % 24), "target_load_mw": 100.0})
    folds = rolling_origin_ridge(rows, ("x",), (2022,))
    assert folds[0]["training_rows"] == 8760
    assert folds[0]["test_rows"] == 8760


def test_flexibility_scenarios_are_bounded_and_never_capacity_claims():
    result = data_centre_flexibility_scenarios([100.0 + (hour % 24) for hour in range(8760)])
    assert len(result) == 9
    assert all(item["capacity_claim"] is False for item in result)
    assert all(item["net_peak_mw"] <= item["gross_peak_mw"] for item in result)


def test_stress_classifier_uses_training_threshold_and_reports_no_capacity():
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    rows = []
    for hour in range(24 * 365 * 2):
        timestamp = start + timedelta(hours=hour)
        x = float(hour % 24)
        rows.append({"timestamp": timestamp.isoformat(), "x": x, "target_load_mw": 100 + x})
    result = rolling_stress_classifier(rows, ("x",), (2022,))[0]
    assert result["capacity_claim"] is False
    assert 0 <= result["brier_score"] <= 1
