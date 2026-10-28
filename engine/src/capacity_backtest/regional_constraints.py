"""Leakage-safe regional constraint rows and transparent temporal classifiers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import sqrt

from .events import GridEvent, known_events


def _is_constraint(event: GridEvent) -> bool:
    if event.status == "cancelled":
        return False
    if "redispatch" in event.kind:
        return event.power_mw is not None and event.power_mw > 0
    return True


@dataclass(frozen=True)
class RegionalHourlyRow:
    issue_time: datetime
    region: str
    horizon_hours: int
    active_event_count: int
    recent_event_count_24h: int
    known_power_mw: float | None
    unknown_power_event_count: int
    source_available: bool
    revision_complete: bool
    target_event: bool | None
    target_resolution: str


def build_regional_rows(
    issue_times: Iterable[datetime],
    events: list[GridEvent],
    region: str,
    *,
    horizon_hours: int = 24,
    source_available: bool,
    revision_complete: bool,
) -> list[RegionalHourlyRow]:
    """Build rows using only revisions published by each issue time.

    Targets are unavailable unless the source is known to distinguish a valid empty
    response from failed/unavailable collection and revision history is complete.
    """
    rows = []
    regional = [event for event in events if event.region == region or event.area == region]
    for issue_time in sorted(issue_times):
        visible = known_events(regional, issue_time)
        issue_utc = issue_time.astimezone(timezone.utc)
        active = [
            e
            for e in visible
            if e.starts_at.astimezone(timezone.utc)
            <= issue_utc
            < e.ends_at.astimezone(timezone.utc)
            and _is_constraint(e)
        ]
        recent = [
            e
            for e in visible
            if issue_utc - timedelta(hours=24) <= e.starts_at.astimezone(timezone.utc) < issue_utc
            and _is_constraint(e)
        ]
        power = [e.power_mw for e in active if e.power_mw is not None]
        future_end = issue_time + timedelta(hours=horizon_hours)
        target = None
        if source_available and revision_complete:
            # Outcome labels use the full preserved record set, not future revisions of an
            # earlier record. A caller must supply an admissible publication archive.
            target = any(
                issue_utc
                < e.starts_at.astimezone(timezone.utc)
                <= future_end.astimezone(timezone.utc)
                for e in regional
                if _is_constraint(e)
            )
        resolutions = {e.geographic_resolution.value for e in regional}
        rows.append(
            RegionalHourlyRow(
                issue_time,
                region,
                horizon_hours,
                len(active),
                len(recent),
                sum(power) if power else None,
                sum(e.power_mw is None for e in active),
                source_available,
                revision_complete,
                target,
                next(iter(resolutions)) if len(resolutions) == 1 else "mixed_or_unknown",
            )
        )
    return rows


def classification_metrics(
    actual: list[int], probability: list[float], threshold: float = 0.5
) -> dict[str, float | None]:
    if not actual or len(actual) != len(probability):
        raise ValueError("actual and probability must be non-empty and aligned")
    predicted = [value >= threshold for value in probability]
    tp = sum(bool(a) and p for a, p in zip(actual, predicted))
    fp = sum(not bool(a) and p for a, p in zip(actual, predicted))
    fn = sum(bool(a) and not p for a, p in zip(actual, predicted))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    brier = sum((a - p) ** 2 for a, p in zip(actual, probability)) / len(actual)
    # Explicit, dependency-free expected calibration error over five fixed bins.
    calibration = 0.0
    for index in range(5):
        lower, upper = index / 5, (index + 1) / 5
        selected = [
            i for i, p in enumerate(probability) if lower <= p < upper or (index == 4 and p == 1)
        ]
        if selected:
            confidence = sum(probability[i] for i in selected) / len(selected)
            observed = sum(actual[i] for i in selected) / len(selected)
            calibration += len(selected) / len(actual) * abs(confidence - observed)
    try:
        from sklearn.metrics import average_precision_score, roc_auc_score

        pr_auc = float(average_precision_score(actual, probability)) if any(actual) else None
        roc_auc = float(roc_auc_score(actual, probability)) if len(set(actual)) == 2 else None
    except ImportError:
        pr_auc = roc_auc = None
    return {
        "precision": precision,
        "recall": recall,
        "false_negative_rate": fn / sum(actual) if sum(actual) else None,
        "brier_score": brier,
        "calibration_error": calibration,
        "rmse_probability": sqrt(brier),
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
    }


def rolling_event_rate(
    rows: list[RegionalHourlyRow], test_years: Iterable[int]
) -> list[dict[str, object]]:
    """Publication-period holdouts for the minimum historical-event-rate baseline."""
    folds = []
    for year in test_years:
        train = [r for r in rows if r.issue_time.year < year and r.target_event is not None]
        test = [r for r in rows if r.issue_time.year == year and r.target_event is not None]
        if not train or not test:
            continue
        rate = sum(bool(r.target_event) for r in train) / len(train)
        metrics = classification_metrics(
            [int(bool(r.target_event)) for r in test], [rate] * len(test)
        )
        folds.append(
            {
                "test_year": year,
                "model": "historical_event_rate",
                "training_rows": len(train),
                "test_rows": len(test),
                "event_rate": rate,
                **metrics,
            }
        )
    return folds


def rolling_seasonal_rate(
    rows: list[RegionalHourlyRow], test_years: Iterable[int]
) -> list[dict[str, object]]:
    """Prior-period month/weekday/hour rate with historical-rate fallback."""
    folds = []
    for year in test_years:
        train = [r for r in rows if r.issue_time.year < year and r.target_event is not None]
        test = [r for r in rows if r.issue_time.year == year and r.target_event is not None]
        if not train or not test:
            continue
        fallback = sum(bool(r.target_event) for r in train) / len(train)
        counts: dict[tuple[int, int, int], list[int]] = {}
        for row in train:
            key = (row.issue_time.month, row.issue_time.weekday(), row.issue_time.hour)
            counts.setdefault(key, []).append(int(bool(row.target_event)))
        probability = []
        for row in test:
            values = counts.get(
                (row.issue_time.month, row.issue_time.weekday(), row.issue_time.hour)
            )
            probability.append(sum(values) / len(values) if values else fallback)
        folds.append(
            {
                "test_year": year,
                "model": "seasonal_calendar_baseline",
                "training_rows": len(train),
                "test_rows": len(test),
                **classification_metrics([int(bool(r.target_event)) for r in test], probability),
            }
        )
    return folds


def rolling_logistic(
    rows: list[RegionalHourlyRow], test_years: Iterable[int]
) -> list[dict[str, object]]:
    """Fit logistic and prior-period Platt/isotonic calibration in rolling-origin folds."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression

    complete = [r for r in rows if r.target_event is not None and r.source_available]
    folds = []
    for year in test_years:
        training = [r for r in complete if r.issue_time.year < year]
        test = [r for r in complete if r.issue_time.year == year]
        if len(training) < 100 or not test or len({r.target_event for r in training}) < 2:
            continue
        split = max(1, int(len(training) * 0.8))
        fit, calibration = training[:split], training[split:]
        if len({r.target_event for r in calibration}) < 2:
            continue

        def matrix(items: list[RegionalHourlyRow]) -> list[list[float]]:
            return [
                [
                    r.issue_time.hour,
                    r.issue_time.weekday(),
                    r.issue_time.month,
                    r.active_event_count,
                    r.recent_event_count_24h,
                    r.known_power_mw or 0.0,
                    r.unknown_power_event_count,
                ]
                for r in items
            ]

        base = LogisticRegression(max_iter=1_000, class_weight="balanced").fit(
            matrix(fit), [int(bool(r.target_event)) for r in fit]
        )
        for method in ("sigmoid", "isotonic"):
            try:
                from sklearn.frozen import FrozenEstimator

                calibrated = CalibratedClassifierCV(FrozenEstimator(base), method=method, cv=2).fit(
                    matrix(calibration), [int(bool(r.target_event)) for r in calibration]
                )
            except ImportError:  # scikit-learn 1.5 compatibility
                calibrated = CalibratedClassifierCV(base, method=method, cv="prefit").fit(
                    matrix(calibration), [int(bool(r.target_event)) for r in calibration]
                )
            probabilities = calibrated.predict_proba(matrix(test))[:, 1].tolist()
            folds.append(
                {
                    "test_year": year,
                    "model": "logistic_regression",
                    "calibration": method,
                    "training_rows": len(fit),
                    "calibration_rows": len(calibration),
                    "test_rows": len(test),
                    **classification_metrics(
                        [int(bool(r.target_event)) for r in test], probabilities
                    ),
                }
            )
    return folds


def rows_as_dicts(rows: list[RegionalHourlyRow]) -> list[dict[str, object]]:
    return [{**asdict(row), "issue_time": row.issue_time.isoformat()} for row in rows]
