from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from capacity_backtest.phase1.forecasting import (
    COMPONENTS,
    ComponentObservation,
    fit_bottom_up_forecast,
    forecast_metrics,
    rolling_origin_bottom_up,
)

GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_phase1_cases.json").read_text(encoding="utf-8")
)


def training_rows(hours: int = 72) -> list[ComponentObservation]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = {
        "it_load": 30.0,
        "cooling": 8.0,
        "auxiliary": 3.0,
        "battery_charging": 2.0,
        "onsite_generation": 4.0,
    }
    return [
        ComponentObservation(
            timestamp=(start + timedelta(hours=hour)).isoformat(),
            component=component,
            value_mw=value + (hour % 24) * 0.1,
            temperature_c=10 + hour % 12,
        )
        for hour in range(hours)
        for component, value in base.items()
    ]


def test_bottom_up_forecast_is_reconciled_and_probabilistic() -> None:
    issued = datetime(2026, 1, 4, tzinfo=timezone.utc)
    times = [(issued + timedelta(hours=index)).isoformat() for index in range(24)]
    result = fit_bottom_up_forecast(
        training_rows(),
        times,
        issued_at=issued.isoformat(),
        forecast_id="phase1-forecast",
        future_temperature_c=[15.0] * 24,
    )
    assert len(result.components) == GOLDEN["forecast"]["expected_component_count"]
    assert {item.component for item in result.components} == set(COMPONENTS)
    assert result.reconciliation_error_mw == GOLDEN["forecast"]["expected_reconciliation_error_mw"]
    assert len(result.distribution.points) == 24
    for point in result.distribution.points:
        assert list(point.quantiles_mw.values()) == sorted(point.quantiles_mw.values())


def test_bottom_up_forecast_rejects_leakage_and_missing_components() -> None:
    issued = datetime(2026, 1, 4, tzinfo=timezone.utc)
    times = [(issued + timedelta(hours=index)).isoformat() for index in range(24)]
    with pytest.raises(ValueError, match="missing components"):
        fit_bottom_up_forecast(
            [item for item in training_rows() if item.component != "cooling"],
            times,
            issued_at=issued.isoformat(),
            forecast_id="missing",
        )
    leaked = training_rows() + [
        ComponentObservation(issued.isoformat(), "it_load", 30.0)
    ]
    with pytest.raises(ValueError, match="must precede"):
        fit_bottom_up_forecast(
            leaked,
            times,
            issued_at=issued.isoformat(),
            forecast_id="leaked",
        )


def test_forecast_metrics_report_interval_coverage_and_underprediction() -> None:
    issued = datetime(2026, 1, 4, tzinfo=timezone.utc)
    times = [(issued + timedelta(hours=index)).isoformat() for index in range(24)]
    result = fit_bottom_up_forecast(
        training_rows(), times, issued_at=issued.isoformat(), forecast_id="metrics"
    )
    actual = [point.mean_mw + 1 for point in result.distribution.points]
    metrics = forecast_metrics(actual, result.distribution)
    assert metrics["underprediction_rate"] == 1
    assert metrics["maximum_underprediction_mw"] == pytest.approx(1)


def test_bottom_up_rolling_origin_uses_multiple_immutable_vintages() -> None:
    rows = training_rows(144)
    folds = rolling_origin_bottom_up(
        rows,
        ["2026-01-04T00:00:00+00:00", "2026-01-05T00:00:00+00:00"],
        horizon_hours=24,
    )
    assert len(folds) == 2
    assert folds[0].training_rows < folds[1].training_rows
    assert all(fold.test_points == 24 for fold in folds)
    assert all("interval_coverage" in fold.metrics for fold in folds)
