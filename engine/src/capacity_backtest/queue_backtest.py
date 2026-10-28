"""Leakage-safe synthetic queue outcome backtesting."""

from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .storage import atomic_write
from .synthetic_operator import read_synthetic_table

CLASSES = ("approved_firm", "conditional_offer", "rejected_synthetic_constraint")


def build_queue_feature_rows(manifest_path: Path, data_root: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("truth_class") != "synthetic_benchmark":
        raise ValueError("queue backtest accepts only a synthetic benchmark package")
    requests = read_synthetic_table(data_root, manifest, "queue_requests")
    outcomes = {
        row["request_id"]: row
        for row in read_synthetic_table(data_root, manifest, "connection_study_outcomes")
    }
    outages = read_synthetic_table(data_root, manifest, "outages")
    if set(outcomes) != {row["request_id"] for row in requests}:
        raise ValueError("queue requests and outcomes are not one-to-one")
    rows: list[dict[str, Any]] = []
    history: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for request in sorted(requests, key=lambda row: (row["submitted_at"], row["request_id"])):
        submitted = datetime.fromisoformat(request["submitted_at"])
        prior = [
            (old_request, outcome)
            for old_request, outcome in history
            if datetime.fromisoformat(outcome["decision_at"]) <= submitted
        ]
        same_node = [
            pair
            for pair in prior
            if pair[0]["network_id"] == request["network_id"]
            and pair[0]["requested_bus"] == request["requested_bus"]
        ]
        known_outage_ids = {
            outage["event_id"]
            for outage in outages
            if outage["network_id"] == request["network_id"]
            and datetime.fromisoformat(outage["published_at"]) <= submitted
        }
        prior_decisions = Counter(outcome["decision"] for _, outcome in same_node)
        outcome = outcomes[request["request_id"]]
        if datetime.fromisoformat(outcome["decision_at"]) <= submitted:
            raise ValueError("outcome leakage: decision is not later than submission")
        rows.append(
            {
                "request_id": request["request_id"],
                "submitted_at": request["submitted_at"],
                "network_id": request["network_id"],
                "node_id": request["requested_bus"],
                "requested_mw": float(request["requested_mw"]),
                "requested_mva": float(request["requested_mva"]),
                "power_factor": float(request["power_factor"]),
                "target_lead_years": int(request["target_year"]) - submitted.year,
                "reserved_before_mw": float(request["reserved_before_mw"]),
                "prior_decided_requests": len(same_node),
                "prior_requested_mw": sum(float(item[0]["requested_mw"]) for item in same_node),
                "prior_firm_approvals": prior_decisions["approved_firm"],
                "prior_conditional_offers": prior_decisions["conditional_offer"],
                "prior_rejections": prior_decisions["rejected_synthetic_constraint"],
                "known_outage_count": len(known_outage_ids),
                "month_sin": math.sin(2 * math.pi * submitted.month / 12),
                "month_cos": math.cos(2 * math.pi * submitted.month / 12),
                "label": outcome["decision"],
                "firm_mw_offered": float(outcome["firm_mw_offered"]),
                "conditional_mw_offered": float(outcome["conditional_mw_offered"]),
                "evidence_cutoff": request["submitted_at"],
                "truth_class": "synthetic_benchmark",
                "capacity_claim": False,
            }
        )
        history.append((request, outcome))
    return rows


FEATURES = (
    "requested_mw",
    "requested_mva",
    "power_factor",
    "target_lead_years",
    "reserved_before_mw",
    "prior_decided_requests",
    "prior_requested_mw",
    "prior_firm_approvals",
    "prior_conditional_offers",
    "prior_rejections",
    "known_outage_count",
    "month_sin",
    "month_cos",
    "network_id",
    "node_id",
)


def _dict_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{name: row[name] for name in FEATURES} for row in rows]


def _historical_probabilities(train: list[dict[str, Any]], count: int) -> list[list[float]]:
    totals = Counter(row["label"] for row in train)
    denominator = len(train) + len(CLASSES)
    probability = [(totals[name] + 1) / denominator for name in CLASSES]
    return [probability[:] for _ in range(count)]


def _fit_probabilities(
    train: list[dict[str, Any]], test: list[dict[str, Any]], model_name: str
) -> list[list[float]]:
    if model_name == "historical_rate":
        return _historical_probabilities(train, len(test))
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    estimator = (
        LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced", random_state=17)
        if model_name == "logistic"
        else RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=17,
            n_jobs=1,
        )
    )
    pipeline = (
        make_pipeline(DictVectorizer(sparse=True), StandardScaler(with_mean=False), estimator)
        if model_name == "logistic"
        else make_pipeline(DictVectorizer(sparse=True), estimator)
    )
    pipeline.fit(_dict_features(train), [row["label"] for row in train])
    raw = pipeline.predict_proba(_dict_features(test))
    learned = list(pipeline[-1].classes_)
    return [
        [float(values[learned.index(name)]) if name in learned else 0.0 for name in CLASSES]
        for values in raw
    ]


def _calibrated_probabilities(
    train: list[dict[str, Any]], test: list[dict[str, Any]], method: str
) -> list[list[float]]:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    split = max(60, int(len(train) * 0.8))
    if len(train) - split < 20:
        return _fit_probabilities(train, test, "logistic")
    fit, calibration = train[:split], train[split:]
    calibration_probability = _fit_probabilities(fit, calibration, "logistic")
    test_probability = _fit_probabilities(fit, test, "logistic")
    calibrated = [[0.0] * len(CLASSES) for _ in test]
    for class_index, class_name in enumerate(CLASSES):
        actual = [int(row["label"] == class_name) for row in calibration]
        if len(set(actual)) < 2:
            for index, probability in enumerate(test_probability):
                calibrated[index][class_index] = probability[class_index]
            continue
        x = [[probability[class_index]] for probability in calibration_probability]
        test_x = [[probability[class_index]] for probability in test_probability]
        if method == "platt":
            calibrator: Any = LogisticRegression(C=1.0, random_state=17).fit(x, actual)
            values = calibrator.predict_proba(test_x)[:, 1]
        else:
            calibrator = IsotonicRegression(out_of_bounds="clip").fit(
                [item[0] for item in x], actual
            )
            values = calibrator.predict([item[0] for item in test_x])
        for index, value in enumerate(values):
            calibrated[index][class_index] = float(value)
    for values in calibrated:
        total = sum(values)
        if total <= 0:
            values[:] = [1 / len(CLASSES)] * len(CLASSES)
        else:
            values[:] = [value / total for value in values]
    return calibrated


def classification_metrics(
    rows: list[dict[str, Any]], probability: list[list[float]]
) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score

    actual = [row["label"] for row in rows]
    predicted = [
        CLASSES[max(range(len(CLASSES)), key=values.__getitem__)] for values in probability
    ]
    per_class: dict[str, Any] = {}
    brier_terms = []
    average_precision = []
    for class_index, name in enumerate(CLASSES):
        binary = [int(value == name) for value in actual]
        predicted_binary = [int(value == name) for value in predicted]
        tp = sum(a and p for a, p in zip(binary, predicted_binary))
        fp = sum(not a and p for a, p in zip(binary, predicted_binary))
        fn = sum(a and not p for a, p in zip(binary, predicted_binary))
        per_class[name] = {
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "false_negative_rate": fn / (tp + fn) if tp + fn else None,
            "support": sum(binary),
        }
        if len(set(binary)) == 2:
            average_precision.append(
                average_precision_score(binary, [p[class_index] for p in probability])
            )
        brier_terms.extend((a - p[class_index]) ** 2 for a, p in zip(binary, probability))
    bins = []
    calibration_error = 0.0
    confidence = [max(item) for item in probability]
    correct = [int(a == p) for a, p in zip(actual, predicted)]
    for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
        indices = [i for i, value in enumerate(confidence) if lower <= value < lower + 0.2]
        if indices:
            mean_confidence = sum(confidence[i] for i in indices) / len(indices)
            observed = sum(correct[i] for i in indices) / len(indices)
            calibration_error += len(indices) / len(rows) * abs(mean_confidence - observed)
            bins.append(
                {"confidence": mean_confidence, "observed": observed, "count": len(indices)}
            )
    unsafe = sum(a != "approved_firm" and p == "approved_firm" for a, p in zip(actual, predicted))
    return {
        "count": len(rows),
        "per_class": per_class,
        "macro_pr_auc": sum(average_precision) / len(average_precision)
        if average_precision
        else None,
        "multiclass_brier": sum(brier_terms) / len(rows),
        "calibration_error": calibration_error,
        "reliability": bins,
        "unsafe_firm_prediction_rate": unsafe / len(rows),
    }


def run_queue_backtest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 160:
        raise ValueError("at least 160 chronological requests are required")
    folds: list[dict[str, Any]] = []
    model_functions: dict[
        str, Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[list[float]]]
    ] = {
        "historical_rate": lambda train, test: _fit_probabilities(train, test, "historical_rate"),
        "logistic": lambda train, test: _fit_probabilities(train, test, "logistic"),
        "random_forest": lambda train, test: _fit_probabilities(train, test, "random_forest"),
        "logistic_platt": lambda train, test: _calibrated_probabilities(train, test, "platt"),
        "logistic_isotonic": lambda train, test: _calibrated_probabilities(train, test, "isotonic"),
    }
    for cutoff in (160, 220, 280):
        if cutoff >= len(rows):
            continue
        train, test = rows[:cutoff], rows[cutoff : min(len(rows), cutoff + 40)]
        for name, predict in model_functions.items():
            folds.append(
                {
                    "design": "rolling_origin",
                    "fold": f"after-{cutoff}",
                    "model": name,
                    "train_count": len(train),
                    "test_count": len(test),
                    "metrics": classification_metrics(test, predict(train, test)),
                }
            )
    for held_out in sorted({row["network_id"] for row in rows}):
        train = [row for row in rows if row["network_id"] != held_out]
        test = [row for row in rows if row["network_id"] == held_out]
        for name in ("historical_rate", "logistic", "random_forest"):
            folds.append(
                {
                    "design": "leave_one_network_family_out",
                    "fold": held_out,
                    "model": name,
                    "train_count": len(train),
                    "test_count": len(test),
                    "metrics": classification_metrics(test, _fit_probabilities(train, test, name)),
                }
            )
    return {
        "schema_version": "synthetic-queue-backtest-v1",
        "truth_class": "synthetic_benchmark",
        "capacity_claim": False,
        "feature_rows": len(rows),
        "folds": folds,
        "release_gate_passed": False,
        "release_gate_reason": "Synthetic labels cannot establish operational reliability.",
    }


def write_queue_backtest(result: dict[str, Any], destination: Path) -> Path:
    atomic_write(destination, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    return destination


def write_queue_artifacts(
    rows: list[dict[str, Any]], result: dict[str, Any], data_root: Path, run_id: str
) -> dict[str, str]:
    feature_path = data_root / "features" / "synthetic-queue-backtest-v1" / run_id / "rows.jsonl.gz"
    feature_content = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    ).encode()
    atomic_write(feature_path, gzip.compress(feature_content, mtime=0))
    result_path = data_root / "models" / "synthetic-queue-backtest-v1" / run_id / "metrics.json"
    write_queue_backtest(result, result_path)
    return {"features": str(feature_path), "metrics": str(result_path)}
