"""Strict JSON adapter into the existing PCC telemetry contract."""

from __future__ import annotations

import json

from capacity_backtest.phase3.telemetry import PCCMeasurement


def parse_pcc_measurements(content: bytes, *, source_id: str) -> tuple[PCCMeasurement, ...]:
    payload = json.loads(content)
    if not isinstance(payload, list) or not payload:
        raise ValueError("telemetry payload must be a non-empty JSON array")
    measurements = []
    allowed = {
        "measurement_id", "pcc_id", "timestamp", "sequence", "voltage_kv", "current_a",
        "active_power_mw", "reactive_power_mvar", "frequency_hz", "quality",
    }
    for row in payload:
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError("telemetry JSON schema drift")
        measurement = PCCMeasurement(**row, source=source_id)
        measurement.validate()
        measurements.append(measurement)
    if [item.sequence for item in measurements] != sorted(item.sequence for item in measurements):
        raise ValueError("telemetry sequence must be chronological")
    return tuple(measurements)
