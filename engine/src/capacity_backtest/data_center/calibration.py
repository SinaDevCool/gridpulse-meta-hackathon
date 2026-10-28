"""Held-out calibration gates for cooling, battery, and facility balance models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite

import numpy as np
from scipy.optimize import nnls

from capacity_backtest.phase2.battery import BatteryTrajectory
from capacity_backtest.phase2.thermal_workload import CoolingConfig

from .facility import FacilityPowerTrajectory


@dataclass(frozen=True)
class CalibrationMetrics:
    model: str
    training_rows: int
    holdout_rows: int
    median_absolute_percentage_error: float
    p90_absolute_percentage_error: float
    maximum_absolute_error: float | None
    accepted: bool
    blockers: tuple[str, ...]
    fingerprint: str
    component_metrics: tuple[CalibrationMetrics, ...] = ()


@dataclass(frozen=True)
class CoolingCalibration:
    config: CoolingConfig
    ambient_temperature_coefficient_mw_per_c: float
    metrics: CalibrationMetrics
    cooling_load_factor: float = 0.0
    topology: str = "aggregate_unspecified"
    operating_range: tuple[float, float, float, float] | None = None

    def predict(self, it_mw: float, temperature_c: float) -> float:
        if not isfinite(it_mw) or not isfinite(temperature_c) or it_mw < 0:
            raise ValueError("cooling prediction requires finite physical inputs")
        if self.operating_range is not None:
            it_min, it_max, temp_min, temp_max = self.operating_range
            if not it_min <= it_mw <= it_max or not temp_min <= temperature_c <= temp_max:
                raise ValueError("cooling prediction is outside the calibrated operating range")
        return max(0.0, self.config.baseline_power_mw + self.cooling_load_factor * it_mw
                   + self.ambient_temperature_coefficient_mw_per_c * temperature_c)


def _metrics(
    model: str,
    actual: tuple[float, ...],
    predicted: tuple[float, ...],
    *,
    training_rows: int,
    maximum_median_fraction: float,
    maximum_p90_fraction: float,
) -> CalibrationMetrics:
    if not actual or len(actual) != len(predicted):
        raise ValueError("calibration actual and predicted values must align")
    if any(not isfinite(v) for v in (*actual, *predicted, maximum_median_fraction, maximum_p90_fraction)):
        raise ValueError("calibration requires finite observations and thresholds")
    if min(maximum_median_fraction, maximum_p90_fraction) < 0:
        raise ValueError("calibration thresholds must be nonnegative")
    absolute = [abs(a - p) for a, p in zip(actual, predicted)]
    fractions = [error / abs(a) if abs(a) > 1e-9 else float(error > 1e-9) for a, error in zip(actual, absolute)]
    ordered = sorted(fractions)
    median = ordered[len(ordered) // 2]
    p90 = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
    blockers = []
    if median > maximum_median_fraction:
        blockers.append("median_error")
    if p90 > maximum_p90_fraction:
        blockers.append("p90_error")
    fingerprint = hashlib.sha256(json.dumps({"actual": actual, "predicted": predicted}, sort_keys=True).encode()).hexdigest()
    return CalibrationMetrics(model, training_rows, len(actual), median, p90, max(absolute), not blockers, tuple(blockers), fingerprint)


def calibrate_cooling(
    training_it_mw: tuple[float, ...],
    training_temperature_c: tuple[float, ...],
    training_cooling_mw: tuple[float, ...],
    holdout_it_mw: tuple[float, ...],
    holdout_temperature_c: tuple[float, ...],
    holdout_cooling_mw: tuple[float, ...],
    *, topology: str = "aggregate_unspecified",
) -> CoolingCalibration:
    if topology not in {"aggregate_unspecified", "air", "direct_to_chip", "immersion", "hybrid"}:
        raise ValueError("unsupported cooling topology")
    if not training_it_mw or not (
        len(training_it_mw) == len(training_temperature_c) == len(training_cooling_mw)
    ) or not (len(holdout_it_mw) == len(holdout_temperature_c) == len(holdout_cooling_mw)):
        raise ValueError("cooling calibration series are invalid")
    matrix = np.asarray([[1.0, it, temperature] for it, temperature in zip(training_it_mw, training_temperature_c)])
    if not np.isfinite(matrix).all() or not np.isfinite(training_cooling_mw).all():
        raise ValueError("cooling calibration requires finite measurements")
    if min(training_it_mw) < 0 or min(training_cooling_mw) < 0:
        raise ValueError("cooling calibration requires nonnegative power")
    operating_range = (min(training_it_mw), max(training_it_mw), min(training_temperature_c), max(training_temperature_c))
    coefficients = nnls(matrix, np.asarray(training_cooling_mw))[0]
    baseline, load_factor, temperature_factor = (max(0.0, float(value)) for value in coefficients)
    predicted = tuple(
        max(0.0, baseline + load_factor * it + temperature_factor * temperature)
        for it, temperature in zip(holdout_it_mw, holdout_temperature_c)
    )
    config = CoolingConfig(
        baseline, 0.0, 0.0, maximum_thermal_debt_mwh=0.0,
        recovery_power_mw=0.0,
    )
    metrics = _metrics("cooling", holdout_cooling_mw, predicted, training_rows=len(training_it_mw), maximum_median_fraction=0.10, maximum_p90_fraction=0.15)
    blockers = list(metrics.blockers)
    if np.linalg.matrix_rank(matrix) < 3:
        blockers.append("unidentifiable_cooling_coefficients")
    if any(not operating_range[0] <= it <= operating_range[1] or not operating_range[2] <= temp <= operating_range[3]
           for it, temp in zip(holdout_it_mw, holdout_temperature_c)):
        blockers.append("holdout_outside_training_range")
    from dataclasses import replace
    metrics = replace(metrics, accepted=not blockers, blockers=tuple(blockers))
    return CoolingCalibration(
        config, temperature_factor,
        metrics,
        cooling_load_factor=load_factor,
        topology=topology, operating_range=operating_range,
    )


def validate_battery_calibration(
    trajectory: BatteryTrajectory,
    observed_soc_mwh: tuple[float, ...],
    observed_power_mw: tuple[float, ...],
) -> CalibrationMetrics:
    if len(trajectory.points) != len(observed_soc_mwh) or len(observed_power_mw) != len(observed_soc_mwh):
        raise ValueError("battery calibration observations must align")
    components = (
        _metrics("battery_soc_mwh", observed_soc_mwh, tuple(p.soc_mwh for p in trajectory.points),
                 training_rows=0, maximum_median_fraction=0.05, maximum_p90_fraction=0.10),
        _metrics("battery_power_mw", observed_power_mw, tuple(p.delivered_power_mw for p in trajectory.points),
                 training_rows=0, maximum_median_fraction=0.05, maximum_p90_fraction=0.10),
    )
    # Gate each measurement boundary separately: MW errors cannot hide behind SOC MWh.
    blockers = tuple(f"{m.model}:{code}" for m in components for code in m.blockers)
    return CalibrationMetrics("battery", 0, len(observed_soc_mwh),
        max(m.median_absolute_percentage_error for m in components),
        max(m.p90_absolute_percentage_error for m in components),
        None, not blockers, blockers,
        hashlib.sha256(json.dumps([m.fingerprint for m in components]).encode()).hexdigest(),
        components)



def validate_facility_calibration(
    trajectory: FacilityPowerTrajectory,
    observed_grid_import_mw: tuple[float, ...],
) -> CalibrationMetrics:
    predicted = tuple(point.grid_import_mw for point in trajectory.points)
    return _metrics("facility", observed_grid_import_mw, predicted, training_rows=0, maximum_median_fraction=0.05, maximum_p90_fraction=0.10)
