"""Rolling-origin experimental modelling for 50Hertz control-area constraint risk."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .regional_constraints import classification_metrics
from .storage import atomic_write

FEATURES = (
    "hour",
    "weekday",
    "month",
    "redispatch_mw_lag_1h",
    "redispatch_mw_lag_24h",
    "redispatch_mw_lag_168h",
    "active_intervals_lag_1h",
    "active_intervals_lag_24h",
    "active_intervals_lag_168h",
)
TARGET = "target_constraint"


def _load(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        row["timestamp"] = datetime.fromisoformat(row["issue_time"])
        if row[TARGET] is not None and all(row[name] is not None for name in FEATURES):
            rows.append(row)
    return rows


def _matrix(rows: list[dict[str, Any]]) -> list[list[float]]:
    return [[float(row[name]) for name in FEATURES] for row in rows]


def _actual(rows: list[dict[str, Any]]) -> list[int]:
    return [int(bool(row[TARGET])) for row in rows]


def _reliability(actual: list[int], probabilities: list[float]) -> list[dict[str, float | int]]:
    result = []
    for index in range(10):
        lower, upper = index / 10, (index + 1) / 10
        selected = [
            position
            for position, value in enumerate(probabilities)
            if lower <= value < upper or (index == 9 and value == 1)
        ]
        if selected:
            result.append(
                {
                    "lower": lower,
                    "upper": upper,
                    "count": len(selected),
                    "mean_probability": sum(probabilities[i] for i in selected) / len(selected),
                    "observed_rate": sum(actual[i] for i in selected) / len(selected),
                }
            )
    return result


def _season(month: int) -> str:
    return (
        "winter"
        if month in {12, 1, 2}
        else "spring"
        if month in {3, 4, 5}
        else "summer"
        if month in {6, 7, 8}
        else "autumn"
    )


def _calibrated_probabilities(
    model: object,
    calibration_x: list[list[float]],
    calibration_y: list[int],
    test_x: list[list[float]],
    method: str,
) -> list[float]:
    from sklearn.calibration import CalibratedClassifierCV

    try:
        from sklearn.frozen import FrozenEstimator

        calibrated = CalibratedClassifierCV(FrozenEstimator(model), method=method).fit(
            calibration_x, calibration_y
        )
    except ImportError:
        calibrated = CalibratedClassifierCV(model, method=method, cv="prefit").fit(
            calibration_x, calibration_y
        )
    return calibrated.predict_proba(test_x)[:, 1].tolist()


def run_constraint_models(feature_path: Path, data_root: Path) -> dict[str, object]:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    rows = _load(feature_path)
    dataset_quality = json.loads((feature_path.parent / "quality.json").read_text(encoding="utf-8"))
    years = sorted({row["timestamp"].year for row in rows})
    folds = []
    predictions = []
    for year in years[1:]:
        prior = [row for row in rows if row["timestamp"].year < year]
        test = [row for row in rows if row["timestamp"].year == year]
        if len(prior) < 1_000 or not test or len(set(_actual(prior))) < 2:
            continue
        split = int(len(prior) * 0.8)
        fit, calibration = prior[:split], prior[split:]
        if len(set(_actual(fit))) < 2 or len(set(_actual(calibration))) < 2:
            continue
        fit_x, fit_y = _matrix(fit), _actual(fit)
        calibration_x, calibration_y = _matrix(calibration), _actual(calibration)
        test_x, test_y = _matrix(test), _actual(test)
        historical_rate = sum(_actual(prior)) / len(prior)
        baseline = [historical_rate] * len(test)
        folds.append(
            {
                "test_year": year,
                "model": "historical_event_rate",
                "training_rows": len(prior),
                "test_rows": len(test),
                "event_rate": historical_rate,
                **classification_metrics(test_y, baseline),
                "reliability": _reliability(test_y, baseline),
            }
        )
        seasonal_counts: dict[tuple[int, int, int], list[int]] = {}
        for row in prior:
            key = (row["month"], row["weekday"], row["hour"])
            seasonal_counts.setdefault(key, []).append(int(bool(row[TARGET])))
        seasonal = [
            (
                sum(values) / len(values)
                if (values := seasonal_counts.get((row["month"], row["weekday"], row["hour"])))
                else historical_rate
            )
            for row in test
        ]
        folds.append(
            {
                "test_year": year,
                "model": "seasonal_calendar_baseline",
                "training_rows": len(prior),
                "test_rows": len(test),
                **classification_metrics(test_y, seasonal),
                "reliability": _reliability(test_y, seasonal),
            }
        )
        estimators = {
            "logistic_regression": make_pipeline(
                StandardScaler(), LogisticRegression(max_iter=2_000, class_weight="balanced")
            ),
            "regularized_tree": HistGradientBoostingClassifier(
                max_iter=150,
                max_leaf_nodes=15,
                learning_rate=0.05,
                l2_regularization=1.0,
                random_state=0,
            ),
        }
        for model_name, model in estimators.items():
            model.fit(fit_x, fit_y)
            for method in ("sigmoid", "isotonic"):
                probability = _calibrated_probabilities(
                    model, calibration_x, calibration_y, test_x, method
                )
                metrics = classification_metrics(test_y, probability)
                season_metrics = {}
                for season in ("winter", "spring", "summer", "autumn"):
                    selected = [i for i, row in enumerate(test) if _season(row["month"]) == season]
                    if selected:
                        season_metrics[season] = classification_metrics(
                            [test_y[i] for i in selected], [probability[i] for i in selected]
                        )
                folds.append(
                    {
                        "test_year": year,
                        "model": model_name,
                        "calibration": method,
                        "training_rows": len(fit),
                        "calibration_rows": len(calibration),
                        "test_rows": len(test),
                        **metrics,
                        "reliability": _reliability(test_y, probability),
                        "by_season": season_metrics,
                    }
                )
                predictions.extend(
                    {
                        "issue_time": row["issue_time"],
                        "test_year": year,
                        "model": model_name,
                        "calibration": method,
                        "actual": actual,
                        "probability": predicted,
                    }
                    for row, actual, predicted in zip(test, test_y, probability)
                )

    source_hash = hashlib.sha256(feature_path.read_bytes()).hexdigest()
    precision_values = [
        float(fold["precision"])
        for fold in folds
        if fold["model"] == "logistic_regression"
        and fold.get("calibration") == "sigmoid"
        and fold["precision"] is not None
    ]
    release = {
        "source_training_admitted": False,
        "yearly_holdouts": len({fold["test_year"] for fold in folds}),
        "yearly_precision_range": (
            max(precision_values) - min(precision_values) if precision_values else None
        ),
        "passed": False,
        "reason": "Source reuse and complete immutable publication-history admission remain unresolved; results are experimental only.",
    }
    report = {
        "schema_version": "50hertz-constraint-model-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_artifact": str(feature_path),
        "feature_sha256": source_hash,
        "features": list(FEATURES),
        "target": TARGET,
        "horizon_hours": dataset_quality["horizon_hours"],
        "geographic_resolution": "50hertz_control_area",
        "folds": folds,
        "release_gate": release,
        "capacity_claim": False,
        "available_capacity_mw": None,
    }
    destination = data_root / "models" / "50hertz-constraint-model-v1" / source_hash
    report_path = destination / "metrics.json"
    prediction_path = (
        data_root
        / "predictions"
        / "50hertz-constraint-model-v1"
        / source_hash
        / "predictions.jsonl"
    )
    atomic_write(report_path, (json.dumps(report, indent=2) + "\n").encode())
    atomic_write(
        prediction_path,
        ("\n".join(json.dumps(row, sort_keys=True) for row in predictions) + "\n").encode(),
    )
    return {
        "metrics": str(report_path),
        "predictions": str(prediction_path),
        "report": report,
    }
