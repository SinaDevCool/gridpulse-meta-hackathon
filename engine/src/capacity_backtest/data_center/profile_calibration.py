"""Evidence-bounded empirical workload power-profile calibration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from itertools import pairwise
from math import isfinite

from capacity_backtest.adapters.workload import WorkloadExecutionObservation
from capacity_backtest.contracts import TruthClass
from capacity_backtest.domain.base import parse_aware_timestamp

from .power_profiles import PiecewiseLinearPowerProfile, PowerThroughputPoint


@dataclass(frozen=True)
class PowerProfileCalibration:
    profile: PiecewiseLinearPowerProfile
    training_executions: int
    holdout_executions: int
    median_power_error_fraction: float
    p90_power_error_fraction: float
    accepted: bool
    blockers: tuple[str, ...]
    fingerprint: str
    median_throughput_error_fraction: float = 0.0
    p90_throughput_error_fraction: float = 0.0
    measured_power_curve: tuple[tuple[int, float, float], ...] = ()


def calibrate_power_profile(
    workload_id: str,
    executions: tuple[WorkloadExecutionObservation, ...],
    *,
    holdout_execution_ids: tuple[str, ...],
    truth_class: TruthClass,
    maximum_median_error_fraction: float = 0.05,
    maximum_p90_error_fraction: float = 0.10,
) -> PowerProfileCalibration:
    if not all(
        isfinite(value) and value >= 0
        for value in (maximum_median_error_fraction, maximum_p90_error_fraction)
    ):
        raise ValueError("calibration error thresholds must be finite and nonnegative")
    relevant = tuple(item for item in executions if item.workload_id == workload_id)
    if len(relevant) < 4 or not holdout_execution_ids:
        raise ValueError("profile calibration requires training and held-out executions")
    holdout_ids = set(holdout_execution_ids)
    train = [item for item in relevant if item.execution_id not in holdout_ids]
    holdout = [item for item in relevant if item.execution_id in holdout_ids]
    if len(train) < 2 or not holdout:
        raise ValueError("profile calibration split is invalid")
    for item in relevant:
        item.validate()
    if len({item.execution_id for item in relevant}) != len(relevant):
        raise ValueError("duplicate execution identities")
    if not holdout_ids.issubset({item.execution_id for item in relevant}):
        raise ValueError("unknown held-out execution")
    if len({item.gpu_model for item in relevant}) != 1:
        raise ValueError("GPU models require separate calibrations")
    if len({(item.configuration_id, item.power_boundary, item.reference_work_duration_minutes) for item in relevant}) != 1:
        raise ValueError("configurations, power boundaries and work references require separate calibrations")
    if relevant[0].power_boundary != "gpu":
        raise ValueError("GPU profiles require GPU-boundary measurements")
    if max(parse_aware_timestamp(item.ended_at, "ended_at") for item in train) > min(
        parse_aware_timestamp(item.started_at, "started_at") for item in holdout
    ):
        raise ValueError("training must precede held-out executions")
    if any(
        not isfinite(value) or value <= 0
        for item in relevant
        for value in (item.power_cap_mw, item.measured_power_mw, item.completed_work_fraction)
    ):
        raise ValueError("calibration requires finite positive measured power and cap")
    grouped: dict[tuple[int, float], list[WorkloadExecutionObservation]] = {}
    for item in train:
        item.validate()
        grouped.setdefault((item.gpu_count, item.power_cap_mw), []).append(item)
    points = []
    measured_curves: dict[int, list[tuple[float, float]]] = {}
    for (gpu_count, cap), rows in sorted(grouped.items()):
        power = sum(item.measured_power_mw for item in rows) / len(rows)
        throughput = sum(item.throughput_fraction() for item in rows) / len(rows)
        points.append(PowerThroughputPoint(gpu_count, cap, throughput))
        measured_curves.setdefault(gpu_count, []).append((cap, power))
    profile = PiecewiseLinearPowerProfile(
        f"calibrated-{workload_id}", workload_id, tuple(points), truth_class
    )
    profile.validate()
    errors, throughput_errors = [], []
    for item in holdout:
        performance = profile.evaluate(item.gpu_count, item.power_cap_mw)
        curve = sorted(measured_curves[item.gpu_count])
        predicted = next((power for cap, power in curve if cap == item.power_cap_mw), None)
        if predicted is None:
            lower, upper = next(
                (a, b) for a, b in pairwise(curve) if a[0] < item.power_cap_mw < b[0]
            )
            weight = (item.power_cap_mw - lower[0]) / (upper[0] - lower[0])
            predicted = lower[1] + weight * (upper[1] - lower[1])
        errors.append(abs(predicted - item.measured_power_mw) / item.measured_power_mw)
        throughput_errors.append(
            abs(performance.throughput_fraction - item.throughput_fraction())
            / item.throughput_fraction()
        )
    ordered = sorted(errors)
    median = ordered[len(ordered) // 2]
    p90 = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
    blockers = []
    if truth_class != TruthClass.SYNTHETIC_DEMONSTRATION and (
        relevant[0].reference_work_duration_minutes is None or relevant[0].configuration_id == "legacy-unspecified"
    ):
        blockers.append("missing_work_reference_or_configuration")
    if median > maximum_median_error_fraction:
        blockers.append("median_power_error")
    if p90 > maximum_p90_error_fraction:
        blockers.append("p90_power_error")
    throughput_errors.sort()
    throughput_median = throughput_errors[len(throughput_errors) // 2]
    throughput_p90 = throughput_errors[
        min(len(throughput_errors) - 1, int(0.9 * len(throughput_errors)))
    ]
    if (
        throughput_median > maximum_median_error_fraction
        or throughput_p90 > maximum_p90_error_fraction
    ):
        blockers.append("throughput_error")
    fingerprint = hashlib.sha256(
        json.dumps([asdict(item) for item in relevant], sort_keys=True).encode()
    ).hexdigest()
    return PowerProfileCalibration(
        profile,
        len(train),
        len(holdout),
        median,
        p90,
        not blockers,
        tuple(blockers),
        fingerprint,
        throughput_median,
        throughput_p90,
        tuple(
            (gpu, cap, power)
            for gpu, curve in sorted(measured_curves.items())
            for cap, power in sorted(curve)
        ),
    )
