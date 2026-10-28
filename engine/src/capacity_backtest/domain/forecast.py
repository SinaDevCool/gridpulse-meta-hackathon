"""Probabilistic forecast contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .base import DomainContract, parse_aware_timestamp, require_non_empty

FORECAST_SCHEMA_VERSION = "gridpulse-forecast-distribution-v1"


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: str
    mean_mw: float
    quantiles_mw: dict[str, float]

    def validate(self) -> None:
        parse_aware_timestamp(self.timestamp, "forecast timestamp")
        if self.mean_mw < 0:
            raise ValueError("forecast mean cannot be negative")
        previous = None
        for label, value in sorted(self.quantiles_mw.items(), key=lambda item: float(item[0])):
            quantile = float(label)
            if not 0 < quantile < 1 or value < 0:
                raise ValueError("forecast quantiles must be in (0, 1) with non-negative values")
            if previous is not None and value < previous:
                raise ValueError("forecast quantiles must be monotonic")
            previous = value


@dataclass(frozen=True)
class ForecastDistribution(DomainContract):
    forecast_id: str
    issued_at: str
    component: str
    points: tuple[ForecastPoint, ...]
    model_version: str
    schema_version: str = FORECAST_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != FORECAST_SCHEMA_VERSION:
            raise ValueError("unsupported forecast schema")
        require_non_empty(self.forecast_id, "forecast_id")
        require_non_empty(self.component, "component")
        require_non_empty(self.model_version, "model_version")
        issued = parse_aware_timestamp(self.issued_at, "issued_at")
        if not self.points:
            raise ValueError("forecast requires at least one point")
        timestamps = []
        for point in self.points:
            point.validate()
            timestamp = parse_aware_timestamp(point.timestamp, "forecast timestamp")
            if timestamp < issued:
                raise ValueError("forecast point cannot precede issue time")
            timestamps.append(timestamp)
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise ValueError("forecast points must have unique chronological timestamps")
