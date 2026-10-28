"""Empirical piecewise-linear workload power and throughput profiles."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain.base import DomainContract


@dataclass(frozen=True)
class PowerThroughputPoint:
    gpu_count: int
    power_cap_mw: float
    throughput_fraction: float

    def validate(self) -> None:
        if self.gpu_count <= 0 or self.power_cap_mw <= 0:
            raise ValueError("power-profile GPU and power values must be positive")
        if not 0 < self.throughput_fraction <= 1:
            raise ValueError("throughput fraction must be in (0, 1]")


@dataclass(frozen=True)
class WorkloadPerformance:
    gpu_count: int
    power_mw: float
    throughput_fraction: float
    runtime_multiplier: float


@dataclass(frozen=True)
class PiecewiseLinearPowerProfile(DomainContract):
    profile_id: str
    workload_id: str
    points: tuple[PowerThroughputPoint, ...]
    truth_class: TruthClass
    schema_version: str = "gridpulse-piecewise-power-profile-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-piecewise-power-profile-v1":
            raise ValueError("unsupported power-profile schema")
        if not self.profile_id or not self.workload_id or len(self.points) < 2:
            raise ValueError("power profile requires identities and at least two points")
        coerce_truth_class(self.truth_class)
        groups: dict[int, list[PowerThroughputPoint]] = {}
        for point in self.points:
            point.validate()
            groups.setdefault(point.gpu_count, []).append(point)
        for rows in groups.values():
            ordered = sorted(rows, key=lambda item: item.power_cap_mw)
            if len(ordered) < 2 or len({item.power_cap_mw for item in ordered}) != len(ordered):
                raise ValueError("each GPU-count curve requires unique power points")
            if any(b.throughput_fraction < a.throughput_fraction for a, b in pairwise(ordered)):
                raise ValueError("throughput must be monotonic with power")

    def evaluate(self, gpu_count: int, power_cap_mw: float) -> WorkloadPerformance:
        self.validate()
        curve = sorted(
            (point for point in self.points if point.gpu_count == gpu_count),
            key=lambda item: item.power_cap_mw,
        )
        if not curve:
            raise ValueError("requested GPU count has no empirical curve")
        if power_cap_mw < curve[0].power_cap_mw or power_cap_mw > curve[-1].power_cap_mw:
            raise ValueError("power-profile extrapolation is prohibited")
        for point in curve:
            if abs(point.power_cap_mw - power_cap_mw) <= 1e-12:
                throughput = point.throughput_fraction
                break
        else:
            lower, upper = next(
                (a, b)
                for a, b in pairwise(curve)
                if a.power_cap_mw < power_cap_mw < b.power_cap_mw
            )
            fraction = (power_cap_mw - lower.power_cap_mw) / (
                upper.power_cap_mw - lower.power_cap_mw
            )
            throughput = lower.throughput_fraction + fraction * (
                upper.throughput_fraction - lower.throughput_fraction
            )
        return WorkloadPerformance(gpu_count, power_cap_mw, throughput, 1 / throughput)
