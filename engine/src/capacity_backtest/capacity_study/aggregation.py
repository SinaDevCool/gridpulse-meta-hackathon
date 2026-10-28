"""Single authoritative aggregation of chronological and ensemble capacity results."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contracts import AvailabilityCapacity, CapacityStatistics


@dataclass(frozen=True)
class RealizationEnvelope:
    realization_id: str
    probability_weight: float
    secure_capacity_mw: tuple[float, ...]
    binding_constraints: tuple[str, ...]
    succeeded: bool = True
    capacity_is_lower_bound: bool = False
    pcc_id: str | None = None


def _weighted_quantile(values: list[float], weights: list[float], probability: float) -> float:
    order = np.argsort(np.asarray(values))
    ordered_values = np.asarray(values, dtype=float)[order]
    ordered_weights = np.asarray(weights, dtype=float)[order]
    cumulative = np.cumsum(ordered_weights) / np.sum(ordered_weights)
    return float(np.interp(probability, cumulative, ordered_values))


def _events(shortfalls: list[float], interval_hours: float) -> tuple[int, float]:
    count = 0
    longest = current = 0
    for value in shortfalls:
        if value > 1e-9:
            if current == 0:
                count += 1
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return count, longest * interval_hours


def aggregate_capacity(
    envelopes: list[RealizationEnvelope],
    *,
    requested_capacity_mw: float,
    interval_hours: float,
    availability_levels: tuple[float, ...] = (1.0, 0.999, 0.99, 0.95, 0.90),
) -> CapacityStatistics:
    """Aggregate chronology and uncertainty without conflating their percentiles."""

    if requested_capacity_mw <= 0 or interval_hours <= 0 or not envelopes:
        raise ValueError("capacity aggregation inputs are invalid")
    successful = [item for item in envelopes if item.succeeded and item.secure_capacity_mw]
    total_weight = sum(item.probability_weight for item in envelopes)
    successful_weight = sum(item.probability_weight for item in successful)
    if not successful or total_weight <= 0:
        raise ValueError("no successful capacity realization")
    length = len(successful[0].secure_capacity_mw)
    if any(len(item.secure_capacity_mw) != length for item in successful):
        raise ValueError("realization envelopes must be chronologically aligned")
    firm_by_realization = [min(item.secure_capacity_mw) for item in successful]
    weights = [item.probability_weight for item in successful]
    pooled = [value for item in successful for value in item.secure_capacity_mw]
    duration = tuple(sorted(pooled, reverse=True))
    availability = []
    for level in availability_levels:
        if not 0 < level <= 1:
            raise ValueError("availability levels must lie in (0, 1]")
        # Capacity exceeded for ``level`` of chronological observations.
        probability = max(0.0, 1.0 - level)
        availability.append(AvailabilityCapacity(level, float(np.quantile(pooled, probability))))
    representative_index = min(
        range(len(successful)),
        key=lambda index: abs(
            firm_by_realization[index] - _weighted_quantile(firm_by_realization, weights, 0.5)
        ),
    )
    representative = successful[representative_index]
    shortfalls = [
        max(0.0, requested_capacity_mw - value) for value in representative.secure_capacity_mw
    ]
    event_count, maximum_event = _events(shortfalls, interval_hours)
    binding_counts: dict[str, int] = {}
    for item in successful:
        for constraint in item.binding_constraints:
            binding_counts[constraint] = binding_counts.get(constraint, 0) + 1
    result = CapacityStatistics(
        firm_capacity_mw=_weighted_quantile(firm_by_realization, weights, 0.5),
        minimum_mw=min(pooled),
        maximum_mw=max(pooled),
        p10_mw=_weighted_quantile(firm_by_realization, weights, 0.1),
        p50_mw=_weighted_quantile(firm_by_realization, weights, 0.5),
        p90_mw=_weighted_quantile(firm_by_realization, weights, 0.9),
        availability_capacities=tuple(availability),
        duration_curve_mw=duration,
        requested_capacity_mw=requested_capacity_mw,
        curtailment_hours=sum(value > 1e-9 for value in shortfalls) * interval_hours,
        curtailed_mwh=sum(shortfalls) * interval_hours,
        curtailment_event_count=event_count,
        maximum_event_hours=maximum_event,
        binding_constraint_counts=binding_counts,
        failed_realization_fraction=max(0.0, 1.0 - successful_weight / total_weight),
        lower_bound_realization_fraction=sum(
            item.probability_weight for item in successful if item.capacity_is_lower_bound
        )
        / successful_weight,
    )
    result.validate()
    return result
