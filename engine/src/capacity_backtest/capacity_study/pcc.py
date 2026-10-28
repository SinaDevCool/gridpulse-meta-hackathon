"""Generate traceable PCC hypotheses without treating proximity as confirmation."""

from __future__ import annotations

import math
from typing import Any

from capacity_backtest.contracts import TruthClass

from .contracts import CandidatePCC, PCCStatus


def _distance_km(latitude: float, longitude: float, other_lat: float, other_lon: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(latitude), math.radians(other_lat)
    delta_phi = math.radians(other_lat - latitude)
    delta_lambda = math.radians(other_lon - longitude)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def generate_pcc_hypotheses(
    *,
    site_latitude: float,
    site_longitude: float,
    requested_capacity_mw: float,
    operator_id: str,
    buses: list[dict[str, Any]],
    maximum_candidates: int = 3,
    minimum_voltage_kv: float | None = None,
) -> tuple[CandidatePCC, ...]:
    """Rank public/reconstructed buses as hypotheses; never confirm them by distance."""

    if requested_capacity_mw <= 0 or maximum_candidates <= 0:
        raise ValueError("capacity and candidate count must be positive")
    inferred_minimum = 110.0 if requested_capacity_mw >= 20 else 20.0
    voltage_floor = minimum_voltage_kv or inferred_minimum
    candidates = []
    for bus in buses:
        if "latitude" not in bus or "longitude" not in bus:
            continue
        voltage = float(bus.get("vn_kv", 0))
        if voltage < voltage_floor:
            continue
        distance = _distance_km(
            site_latitude,
            site_longitude,
            float(bus["latitude"]),
            float(bus["longitude"]),
        )
        voltage_fit = min(1.0, voltage / max(voltage_floor, 1.0))
        confidence = max(0.05, min(0.75, 0.45 * math.exp(-distance / 30) + 0.2 * voltage_fit))
        bus_id = str(bus["id"])
        candidates.append(
            CandidatePCC(
                pcc_id=f"pcc-hypothesis-{bus_id}",
                bus_id=bus_id,
                operator_id=operator_id,
                voltage_kv=voltage,
                latitude=float(bus["latitude"]),
                longitude=float(bus["longitude"]),
                distance_km=distance,
                status=PCCStatus.GEOGRAPHIC_HYPOTHESIS,
                confidence=confidence,
                truth_class=TruthClass.EXPERIMENTAL_ESTIMATE,
            )
        )
    selected = tuple(
        sorted(candidates, key=lambda item: (-item.confidence, item.distance_km or 0))[
            :maximum_candidates
        ]
    )
    if not selected:
        raise ValueError("no geographically and electrically plausible PCC hypotheses")
    for item in selected:
        item.validate()
    return selected
