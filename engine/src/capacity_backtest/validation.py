"""Chronological evaluation and conservative stress scenarios."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from .contracts import TruthClass
from .models import RidgeBaseline, regression_metrics
from .scenarios import Battery, apply_rechargeable_battery


@dataclass(frozen=True)
class RollingFold:
    test_year: int
    training_rows: int
    test_rows: int
    mae_mw: float
    rmse_mw: float


def rolling_stress_classifier(
    rows: list[dict[str, object]], features: tuple[str, ...], years: tuple[int, ...]
) -> list[dict[str, object]]:
    """Predict a training-defined high-load event and report calibration-sensitive metrics."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    complete = [
        row for row in rows
        if row["target_load_mw"] is not None and all(row[key] is not None for key in features)
    ]
    results = []
    for year in years:
        train = [row for row in complete if datetime.fromisoformat(str(row["timestamp"])).year < year]
        test = [row for row in complete if datetime.fromisoformat(str(row["timestamp"])).year == year]
        if not train or len(test) < 24 * 300:
            continue
        sorted_target = sorted(float(row["target_load_mw"]) for row in train)
        threshold = sorted_target[int(len(sorted_target) * 0.95)]
        train_x = [[float(row[key]) for key in features] for row in train]
        train_y = [int(float(row["target_load_mw"]) > threshold) for row in train]
        test_x = [[float(row[key]) for key in features] for row in test]
        actual = [int(float(row["target_load_mw"]) > threshold) for row in test]
        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=1_000, class_weight="balanced"),
        ).fit(train_x, train_y)
        probability = model.predict_proba(test_x)[:, 1].tolist()
        predicted = [int(value >= 0.5) for value in probability]
        true_positive = sum(a and p for a, p in zip(actual, predicted))
        false_positive = sum(not a and p for a, p in zip(actual, predicted))
        false_negative = sum(a and not p for a, p in zip(actual, predicted))
        bins = []
        for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
            indices = [index for index, value in enumerate(probability) if lower <= value < lower + 0.2]
            if indices:
                bins.append({
                    "mean_probability": sum(probability[index] for index in indices) / len(indices),
                    "observed_rate": sum(actual[index] for index in indices) / len(indices),
                    "count": len(indices),
                })
        results.append({
            "test_year": year, "training_threshold_mw": threshold,
            "brier_score": sum((a - p) ** 2 for a, p in zip(actual, probability)) / len(actual),
            "precision": true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0,
            "recall": true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0,
            "false_negative_rate": false_negative / sum(actual) if sum(actual) else 0.0,
            "calibration_bins": bins, "truth_class": "derived_public_context",
            "capacity_claim": False,
        })
    return results


def rolling_origin_ridge(
    rows: list[dict[str, object]], features: tuple[str, ...], years: tuple[int, ...]
) -> list[dict[str, object]]:
    complete = [
        row for row in rows
        if row["target_load_mw"] is not None and all(row[key] is not None for key in features)
    ]
    folds = []
    for year in years:
        train = [row for row in complete if datetime.fromisoformat(str(row["timestamp"])).year < year]
        test = [row for row in complete if datetime.fromisoformat(str(row["timestamp"])).year == year]
        if not train or len(test) < 24 * 300:
            continue
        train_x = [[float(row[key]) for key in features] for row in train]
        train_y = [float(row["target_load_mw"]) for row in train]
        test_x = [[float(row[key]) for key in features] for row in test]
        test_y = [float(row["target_load_mw"]) for row in test]
        prediction = RidgeBaseline().fit_predict(train_x, train_y, test_x)
        metrics = regression_metrics(test_y, prediction.predictions)
        folds.append(asdict(RollingFold(year, len(train), len(test), metrics["mae"], metrics["rmse"])))
    return folds


def annual_stress_scenarios(load: list[float]) -> list[dict[str, object]]:
    if len(load) != 8760:
        raise ValueError("stress scenarios require a complete 8,760-hour year")
    peak = max(load)
    definitions = (
        ("observed_context", 1.0, 0.0),
        ("high_system_load", 1.1, 0.0),
        ("plus_50_mw_site", 1.0, 50.0),
        ("plus_100_mw_site", 1.0, 100.0),
        ("plus_200_mw_site", 1.0, 200.0),
    )
    results = []
    for name, scale, addition in definitions:
        values = [value * scale + addition for value in load]
        results.append({
            "scenario": name,
            "peak_mw": max(values),
            "mean_mw": sum(values) / len(values),
            "hours_above_observed_peak": sum(value > peak for value in values),
            "truth_class": TruthClass.SYNTHETIC_DEMONSTRATION.value,
            "capacity_claim": False,
        })
    return results


def data_centre_flexibility_scenarios(load: list[float]) -> list[dict[str, object]]:
    """Compare continuous site loads and bounded flexibility against a public-context threshold."""
    if len(load) != 8760:
        raise ValueError("flexibility scenarios require a complete 8,760-hour year")
    threshold = sorted(load)[int(len(load) * 0.95)]
    results = []
    for site_mw in (50.0, 100.0, 200.0):
        gross = [value + site_mw for value in load]
        for flexible_share in (0.0, 0.05, 0.10):
            reduced = [value - site_mw * flexible_share if value > threshold else value for value in gross]
            battery = Battery(site_mw * 0.25, site_mw, 0.9, site_mw, site_mw * 0.1, 0.9)
            dispatched = apply_rechargeable_battery(reduced, threshold, battery)
            results.append({
                "site_load_mw": site_mw, "interruptible_share": flexible_share,
                "battery_power_mw": battery.power_mw, "battery_energy_mwh": battery.energy_mwh,
                "gross_peak_mw": max(gross), "net_peak_mw": max(dispatched["net_load_mw"]),
                "hours_above_context_threshold": dispatched["hours_above_threshold"],
                "equivalent_battery_cycles": dispatched["equivalent_cycles"],
                "truth_class": TruthClass.SYNTHETIC_DEMONSTRATION.value,
                "capacity_claim": False,
            })
    return results
