"""Leakage-safe hourly observations and feature construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise


@dataclass(frozen=True)
class HourlyObservation:
    timestamp: datetime
    region_id: str
    load_mw: float | None
    wind_mw: float | None = None
    solar_mw: float | None = None
    temperature_c: float | None = None
    congestion: bool | None = None


def validate_hourly(observations: list[HourlyObservation]) -> list[str]:
    warnings: list[str] = []
    ordered = sorted(observations, key=lambda item: item.timestamp)
    if len({item.timestamp for item in ordered}) != len(ordered):
        raise ValueError("duplicate timestamps")
    for previous, current in pairwise(ordered):
        if current.timestamp - previous.timestamp != timedelta(hours=1):
            warnings.append("time series contains missing hourly intervals")
            break
    return warnings


def build_lagged_rows(observations: list[HourlyObservation], lags: tuple[int, ...] = (1, 24, 168)) -> list[dict[str, object]]:
    """Build rows using past values only; missing information remains None."""
    ordered = sorted(observations, key=lambda item: item.timestamp)
    lookup = {(item.region_id, item.timestamp): item for item in ordered}
    rows: list[dict[str, object]] = []
    for item in ordered:
        features: dict[str, object] = {
            "timestamp": item.timestamp.isoformat(),
            "region_id": item.region_id,
            "hour": item.timestamp.hour,
            "weekday": item.timestamp.weekday(),
            "month": item.timestamp.month,
            "temperature_c": item.temperature_c,
            "target_load_mw": item.load_mw,
            "target_congestion": item.congestion,
        }
        for lag in lags:
            prior = lookup.get((item.region_id, item.timestamp - timedelta(hours=lag)))
            features[f"load_lag_{lag}h"] = prior.load_mw if prior else None
            features[f"wind_lag_{lag}h"] = prior.wind_mw if prior else None
            features[f"solar_lag_{lag}h"] = prior.solar_mw if prior else None
            features[f"temperature_lag_{lag}h"] = prior.temperature_c if prior else None
        rows.append(features)
    return rows


def chronological_split(rows: list[dict[str, object]], final_year: int) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    training, test = [], []
    for row in rows:
        year = datetime.fromisoformat(str(row["timestamp"])).year
        (test if year == final_year else training).append(row)
    if not training or not test:
        raise ValueError("split requires training data and a complete held-out year")
    if max(str(row["timestamp"]) for row in training) >= min(str(row["timestamp"]) for row in test):
        raise ValueError("training overlaps held-out period")
    return training, test
