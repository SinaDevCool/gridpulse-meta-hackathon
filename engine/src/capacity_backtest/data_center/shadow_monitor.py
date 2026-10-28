"""Transparent planned-versus-observed residual and fail-safe monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import zip_longest

from capacity_backtest.phase3.failsafe import (
    FailSafeMachine,
    OperationalEvent,
    OperationalState,
)


@dataclass(frozen=True)
class ShadowStatePoint:
    interval_index: int
    planned_grid_import_mw: float
    observed_grid_import_mw: float
    absolute_residual_mw: float
    residual_fraction: float
    uncertainty_band_mw: float
    inside_band: bool
    consecutive_divergence_count: int


@dataclass(frozen=True)
class ShadowDivergenceAssessment:
    points: tuple[ShadowStatePoint, ...]
    classification: str
    final_operational_state: OperationalState
    conditional_flexibility_allowed: bool
    blockers: tuple[str, ...]


def assess_shadow_divergence(
    planned_grid_import_mw: tuple[float, ...],
    observed_grid_import_mw: tuple[float, ...],
    *,
    uncertainty_band_mw: tuple[float, ...],
    warning_consecutive_intervals: int = 2,
    safe_limit_consecutive_intervals: int = 3,
    evaluated_at: str,
) -> ShadowDivergenceAssessment:
    size = len(planned_grid_import_mw)
    if not size or len(observed_grid_import_mw) != size or len(uncertainty_band_mw) != size:
        raise ValueError("shadow comparison trajectories must be non-empty and aligned")
    if warning_consecutive_intervals < 1 or safe_limit_consecutive_intervals < warning_consecutive_intervals:
        raise ValueError("shadow divergence thresholds are invalid")
    machine = FailSafeMachine()
    machine.apply(OperationalEvent.ARM, evaluated_at)
    consecutive = 0
    points = []
    for index, values in enumerate(
        zip_longest(planned_grid_import_mw, observed_grid_import_mw, uncertainty_band_mw)
    ):
        planned, observed, band = values
        assert planned is not None and observed is not None and band is not None
        if min(planned, observed, band) < 0:
            raise ValueError("shadow comparison powers cannot be negative")
        residual = abs(planned - observed)
        inside = residual <= band + 1e-9
        consecutive = 0 if inside else consecutive + 1
        scale = max(planned, observed)
        points.append(ShadowStatePoint(
            index, planned, observed, residual, residual / scale if scale else 0.0,
            band, inside, consecutive,
        ))
    maximum = max(point.consecutive_divergence_count for point in points)
    blockers = []
    if maximum >= safe_limit_consecutive_intervals:
        machine.apply(OperationalEvent.DELIVERY_FAILED, evaluated_at, "persistent_model_divergence")
        classification = "safe_limit"
        blockers.append("persistent_model_divergence")
    elif maximum >= warning_consecutive_intervals:
        machine.apply(OperationalEvent.RESOURCE_UNAVAILABLE, evaluated_at, "model_divergence")
        classification = "degraded"
        blockers.append("model_divergence")
    else:
        classification = "normal"
    return ShadowDivergenceAssessment(
        tuple(points), classification, machine.state, machine.conditional_dispatch_allowed,
        tuple(blockers),
    )
