"""Transparent forecast baselines and a fail-closed Prior Labs TabPFN adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PredictionResult:
    status: str
    predictions: list[float]
    model: str
    limitations: list[str]


class Regressor(Protocol):
    def fit_predict(self, train_x: list[list[float]], train_y: list[float], test_x: list[list[float]]) -> PredictionResult: ...


class MeanBaseline:
    def fit_predict(self, train_x: list[list[float]], train_y: list[float], test_x: list[list[float]]) -> PredictionResult:
        if not train_y:
            raise ValueError("training targets are empty")
        value = sum(train_y) / len(train_y)
        return PredictionResult("succeeded", [value] * len(test_x), "mean_baseline", [])


class RidgeBaseline:
    def fit_predict(self, train_x: list[list[float]], train_y: list[float], test_x: list[list[float]]) -> PredictionResult:
        from sklearn.linear_model import Ridge

        model = Ridge(alpha=1.0).fit(train_x, train_y)
        return PredictionResult("succeeded", model.predict(test_x).astype(float).tolist(), "ridge", [])


class TabPFNRegressorAdapter:
    """Remote model adapter; never falls back to fabricated predictions."""

    def fit_predict(self, train_x: list[list[float]], train_y: list[float], test_x: list[list[float]]) -> PredictionResult:
        token = os.environ.get("TABPFN_TOKEN")
        if not token:
            return PredictionResult("unavailable", [], "tabpfn", ["TABPFN_TOKEN is not configured."])
        try:
            import numpy as np
            from tabpfn_client import TabPFNRegressor, set_access_token

            set_access_token(token)
            model = TabPFNRegressor()
            model.fit(np.asarray(train_x, dtype=float), np.asarray(train_y, dtype=float))
            predictions = model.predict(np.asarray(test_x, dtype=float))
            return PredictionResult("succeeded", [float(value) for value in predictions], "tabpfn", ["Inputs were processed by the Prior Labs managed service."])
        except (AttributeError, ImportError, OSError, RuntimeError, ValueError) as exc:
            return PredictionResult("failed", [], "tabpfn", [f"Prior Labs request failed: {type(exc).__name__}"])


def regression_metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("actual and predicted values must be non-empty and aligned")
    errors = [abs(a - p) for a, p in zip(actual, predicted)]
    squared = [(a - p) ** 2 for a, p in zip(actual, predicted)]
    return {"mae": sum(errors) / len(errors), "rmse": (sum(squared) / len(squared)) ** 0.5}
