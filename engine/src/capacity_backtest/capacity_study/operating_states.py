"""Build chronological operating states from observed totals and explicit reconstructions."""

from __future__ import annotations

import math
import random

from capacity_backtest.contracts import TruthClass

from .contracts import OperatingStatePoint, OperatingStateSeries


def assemble_operating_states(
    *,
    series_id: str,
    timestamps: list[str],
    regional_load_mw: list[float],
    regional_generation_mw: list[float],
    nodal_load_fraction: float,
    nodal_generation_fraction: float,
    committed_connections_mw: list[float] | None,
    reservations_mw: list[float] | None,
    evidence_cutoff: str,
    active_outage_ids: list[list[str]] | None = None,
    power_factor: float = 0.97,
    interval_hours: float = 1.0,
    truth_class: TruthClass = TruthClass.EXPERIMENTAL_ESTIMATE,
    reconstruction_method: str = "regional-total-constrained-allocation-v1",
) -> OperatingStateSeries:
    size = len(timestamps)
    vectors = (regional_load_mw, regional_generation_mw)
    if not size or any(len(item) != size for item in vectors):
        raise ValueError("timestamps, load and generation must be non-empty and aligned")
    if not 0 <= nodal_load_fraction <= 1 or not 0 <= nodal_generation_fraction <= 1:
        raise ValueError("nodal allocation fractions must lie in [0, 1]")
    if not 0 < power_factor <= 1:
        raise ValueError("power factor must lie in (0, 1]")
    commitments = committed_connections_mw or [0.0] * size
    reservations = reservations_mw or [0.0] * size
    outages = active_outage_ids or [[] for _ in range(size)]
    if len(commitments) != size or len(reservations) != size or len(outages) != size:
        raise ValueError("commitment and reservation vectors must align")
    points = []
    for stamp, load, generation, committed, reserved, active_outages in zip(
        timestamps, regional_load_mw, regional_generation_mw, commitments, reservations, outages
    ):
        background_load = max(0.0, float(load) * nodal_load_fraction)
        background_generation = max(0.0, float(generation) * nodal_generation_fraction)
        gross_load = background_load + float(committed) + float(reserved)
        reactive = gross_load * math.tan(math.acos(power_factor))
        points.append(
            OperatingStatePoint(
                stamp,
                background_load,
                background_generation,
                float(committed),
                float(reserved),
                reactive,
                tuple(str(item) for item in active_outages),
            )
        )
    result = OperatingStateSeries(
        series_id,
        tuple(points),
        truth_class,
        evidence_cutoff,
        reconstruction_method,
        interval_hours,
    )
    result.validate()
    return result


def mock_operator_series(
    *,
    timestamps: list[str],
    evidence_cutoff: str,
    seed: int,
    peak_load_mw: float,
    generation_capacity_mw: float,
    interval_hours: float = 1.0,
) -> OperatingStateSeries:
    """Produce explicit synthetic missing-operator inputs for methodology testing only."""

    if peak_load_mw <= 0 or generation_capacity_mw < 0:
        raise ValueError("mock system powers are invalid")
    rng = random.Random(seed)
    load, generation = [], []
    for index, _ in enumerate(timestamps):
        hour = index % 24
        daily = 0.72 + 0.18 * math.sin((hour - 7) * math.pi / 12)
        load.append(peak_load_mw * max(0.45, daily + rng.uniform(-0.04, 0.04)))
        solar = max(0.0, math.sin((hour - 6) * math.pi / 12))
        generation.append(generation_capacity_mw * solar * rng.uniform(0.75, 1.0))
    return assemble_operating_states(
        series_id=f"mock-operator-{seed}",
        timestamps=timestamps,
        regional_load_mw=load,
        regional_generation_mw=generation,
        nodal_load_fraction=0.08,
        nodal_generation_fraction=0.08,
        committed_connections_mw=None,
        reservations_mw=None,
        evidence_cutoff=evidence_cutoff,
        interval_hours=interval_hours,
        truth_class=TruthClass.SYNTHETIC_DEMONSTRATION,
        reconstruction_method=f"explicit-mock-operator-v1-seed-{seed}",
    )
