"""Leakage-safe bottom-up forecasts with reconciled probabilistic totals."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]

from capacity_backtest.domain import ForecastDistribution, ForecastPoint
from capacity_backtest.domain.base import parse_aware_timestamp, require_non_empty

COMPONENTS = (
    "it_load",
    "cooling",
    "auxiliary",
    "battery_charging",
    "onsite_generation",
)


@dataclass(frozen=True)
class ComponentObservation:
    timestamp: str
    component: str
    value_mw: float
    temperature_c: float | None = None

    def validate(self) -> None:
        parse_aware_timestamp(self.timestamp, "observation timestamp")
        if self.component not in COMPONENTS:
            raise ValueError(f"unsupported data-centre component: {self.component}")
        if self.value_mw < 0:
            raise ValueError("component observations cannot be negative")


@dataclass(frozen=True)
class ComponentModelResult:
    component: str
    predictions_mw: tuple[float, ...]
    residual_quantiles_mw: dict[str, float]
    training_rows: int


@dataclass(frozen=True)
class BottomUpForecast:
    distribution: ForecastDistribution
    components: tuple[ComponentModelResult, ...]
    reconciliation_error_mw: float
    metrics: dict[str, float]


@dataclass(frozen=True)
class RollingOriginFold:
    issued_at: str
    training_rows: int
    test_points: int
    metrics: dict[str, float]


def _features(timestamp: datetime, temperature: float | None) -> list[float]:
    hour = 2 * math.pi * timestamp.hour / 24
    weekday = 2 * math.pi * timestamp.weekday() / 7
    return [
        math.sin(hour),
        math.cos(hour),
        math.sin(weekday),
        math.cos(weekday),
        float(timestamp.month),
        float(temperature if temperature is not None else 15.0),
    ]


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    return float(np.quantile(np.asarray(values, dtype=float), probability))


def fit_bottom_up_forecast(
    observations: list[ComponentObservation],
    forecast_times: list[str],
    *,
    issued_at: str,
    forecast_id: str,
    future_temperature_c: list[float | None] | None = None,
    quantiles: tuple[float, ...] = (0.1, 0.5, 0.9),
    model_version: str = "bottom-up-ridge-v1",
) -> BottomUpForecast:
    """Fit each physical component separately and reconcile to net site demand."""

    require_non_empty(forecast_id, "forecast_id")
    issued = parse_aware_timestamp(issued_at, "issued_at")
    parsed_times = [parse_aware_timestamp(value, "forecast timestamp") for value in forecast_times]
    if not parsed_times or parsed_times != sorted(parsed_times) or len(set(parsed_times)) != len(parsed_times):
        raise ValueError("forecast_times must be unique and chronological")
    if parsed_times[0] < issued:
        raise ValueError("forecast horizon cannot precede issued_at")
    temperatures = future_temperature_c or [None] * len(parsed_times)
    if len(temperatures) != len(parsed_times):
        raise ValueError("future temperatures must align with forecast times")
    if not quantiles or any(not 0 < value < 1 for value in quantiles):
        raise ValueError("quantiles must lie in (0, 1)")
    if tuple(sorted(set(quantiles))) != quantiles:
        raise ValueError("quantiles must be unique and sorted")

    grouped: dict[str, list[ComponentObservation]] = {}
    for row in observations:
        row.validate()
        timestamp = parse_aware_timestamp(row.timestamp, "observation timestamp")
        if timestamp >= issued:
            raise ValueError("training observations must precede forecast issue time")
        grouped.setdefault(row.component, []).append(row)
    missing = set(COMPONENTS) - set(grouped)
    if missing:
        raise ValueError(f"bottom-up forecast is missing components: {sorted(missing)}")

    component_results = []
    component_predictions: dict[str, list[float]] = {}
    component_residual_quantiles: dict[str, dict[str, float]] = {}
    actual, fitted = [], []
    test_x = [_features(timestamp, temperature) for timestamp, temperature in zip(parsed_times, temperatures)]
    for component in COMPONENTS:
        rows = sorted(grouped[component], key=lambda item: item.timestamp)
        if len(rows) < 24:
            raise ValueError(f"component {component} requires at least 24 training rows")
        train_x = [
            _features(parse_aware_timestamp(row.timestamp, "observation timestamp"), row.temperature_c)
            for row in rows
        ]
        train_y = [row.value_mw for row in rows]
        model = Ridge(alpha=1.0).fit(train_x, train_y)
        fitted_values = np.maximum(0.0, model.predict(train_x)).astype(float).tolist()
        predictions = np.maximum(0.0, model.predict(test_x)).astype(float).tolist()
        residuals = [target - prediction for target, prediction in zip(train_y, fitted_values)]
        residual_q = {str(value): _quantile(residuals, value) for value in quantiles}
        component_predictions[component] = predictions
        component_residual_quantiles[component] = residual_q
        component_results.append(
            ComponentModelResult(component, tuple(predictions), residual_q, len(rows))
        )
        actual.extend(train_y)
        fitted.extend(fitted_values)

    points = []
    reconciliation_error = 0.0
    for index, forecast_timestamp in enumerate(forecast_times):
        gross = sum(component_predictions[name][index] for name in COMPONENTS if name != "onsite_generation")
        mean = max(0.0, gross - component_predictions["onsite_generation"][index])
        totals = {}
        for probability in quantiles:
            label = str(probability)
            load_q = sum(
                component_predictions[name][index] + component_residual_quantiles[name][label]
                for name in COMPONENTS
                if name != "onsite_generation"
            )
            generation_q = component_predictions["onsite_generation"][index] + component_residual_quantiles["onsite_generation"][str(1 - probability) if str(1 - probability) in component_residual_quantiles["onsite_generation"] else label]
            totals[label] = max(0.0, load_q - generation_q)
        ordered = sorted(totals, key=float)
        monotonic = 0.0
        for label in ordered:
            monotonic = max(monotonic, totals[label])
            totals[label] = monotonic
        reconciliation_error = max(reconciliation_error, abs(mean - (gross - component_predictions["onsite_generation"][index])))
        points.append(ForecastPoint(forecast_timestamp, mean, totals))
    errors = [a - p for a, p in zip(actual, fitted)]
    metrics = {
        "training_mae_mw": sum(abs(value) for value in errors) / len(errors),
        "training_rmse_mw": math.sqrt(sum(value * value for value in errors) / len(errors)),
        "component_count": float(len(COMPONENTS)),
    }
    distribution = ForecastDistribution(
        forecast_id=forecast_id,
        issued_at=issued_at,
        component="total_site_load",
        points=tuple(points),
        model_version=model_version,
    )
    distribution.validate()
    return BottomUpForecast(distribution, tuple(component_results), reconciliation_error, metrics)


def forecast_metrics(
    actual_mw: list[float], distribution: ForecastDistribution
) -> dict[str, float]:
    """Score point and interval forecasts, emphasizing unsafe underprediction."""

    distribution.validate()
    if len(actual_mw) != len(distribution.points) or not actual_mw:
        raise ValueError("actual observations must align with forecast points")
    errors = [actual - point.mean_mw for actual, point in zip(actual_mw, distribution.points)]
    lower_label = min(distribution.points[0].quantiles_mw, key=float)
    upper_label = max(distribution.points[0].quantiles_mw, key=float)
    covered = [
        point.quantiles_mw[lower_label] <= actual <= point.quantiles_mw[upper_label]
        for actual, point in zip(actual_mw, distribution.points)
    ]
    return {
        "mae_mw": sum(abs(value) for value in errors) / len(errors),
        "rmse_mw": math.sqrt(sum(value * value for value in errors) / len(errors)),
        "underprediction_rate": sum(value > 0 for value in errors) / len(errors),
        "maximum_underprediction_mw": max(max(errors), 0.0),
        "interval_coverage": sum(covered) / len(covered),
    }


def rolling_origin_bottom_up(
    observations: list[ComponentObservation],
    issue_times: list[str],
    *,
    horizon_hours: int = 24,
) -> tuple[RollingOriginFold, ...]:
    """Evaluate immutable forecast vintages without using observations available after issue."""

    if horizon_hours <= 0 or not issue_times:
        raise ValueError("rolling-origin evaluation requires issues and a positive horizon")
    for row in observations:
        row.validate()
    issues = [parse_aware_timestamp(value, "rolling issue time") for value in issue_times]
    if issues != sorted(issues) or len(issues) != len(set(issues)):
        raise ValueError("rolling issue times must be unique and chronological")
    folds = []
    for issue, issue_text in zip(issues, issue_times):
        training = [
            row
            for row in observations
            if parse_aware_timestamp(row.timestamp, "observation timestamp") < issue
        ]
        future_by_timestamp: dict[str, dict[str, ComponentObservation]] = {}
        for row in observations:
            timestamp = parse_aware_timestamp(row.timestamp, "observation timestamp")
            if issue <= timestamp < issue + timedelta(hours=horizon_hours):
                future_by_timestamp.setdefault(row.timestamp, {})[row.component] = row
        complete = [
            (timestamp, values)
            for timestamp, values in sorted(future_by_timestamp.items())
            if set(values) == set(COMPONENTS)
        ]
        if len(complete) != horizon_hours:
            raise ValueError(f"rolling fold {issue_text} does not have a complete held-out horizon")
        forecast_times = [timestamp for timestamp, _ in complete]
        temperatures = [
            next(
                (row.temperature_c for row in values.values() if row.temperature_c is not None),
                None,
            )
            for _, values in complete
        ]
        predicted = fit_bottom_up_forecast(
            training,
            forecast_times,
            issued_at=issue_text,
            forecast_id=f"rolling-{issue.isoformat()}",
            future_temperature_c=temperatures,
        )
        actual = [
            max(
                0.0,
                sum(values[name].value_mw for name in COMPONENTS if name != "onsite_generation")
                - values["onsite_generation"].value_mw,
            )
            for _, values in complete
        ]
        folds.append(
            RollingOriginFold(
                issued_at=issue_text,
                training_rows=len(training),
                test_points=len(actual),
                metrics=forecast_metrics(actual, predicted.distribution),
            )
        )
    return tuple(folds)
