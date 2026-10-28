"""Read-only shadow-verification boundary; it has no command transport capability."""

from __future__ import annotations

from typing import Any

from capacity_backtest.data_center.measurement_boundaries import MeasuredComponent
from capacity_backtest.data_center.observations import ComponentObservation
from capacity_backtest.data_center.security_readiness import (
    ShadowSecurityControls,
    assess_shadow_security,
)
from capacity_backtest.data_center.shadow_monitor import assess_shadow_divergence
from capacity_backtest.data_center.shadow_reporting import build_shadow_operations_snapshot
from capacity_backtest.data_center.telemetry_quality import assess_component_telemetry

from .facility import ENGINE_VERSION, _fingerprint, _serialize

SHADOW_VERIFICATION_REQUEST_SCHEMA = "gridpulse-shadow-verification-request-v1"
SHADOW_VERIFICATION_RESULT_SCHEMA = "gridpulse-shadow-verification-application-result-v1"


def run_shadow_verification(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != SHADOW_VERIFICATION_REQUEST_SCHEMA:
        raise ValueError("unsupported shadow-verification request schema")
    observations = []
    for row in request["observations"]:
        values = dict(row)
        values["component"] = MeasuredComponent(values["component"])
        observations.append(ComponentObservation(**values))
    quality = assess_component_telemetry(
        tuple(observations), reference_times=tuple(request["reference_times"]),
        supplied_energy_mwh=float(request["supplied_energy_mwh"]),
        consumed_energy_mwh=float(request["consumed_energy_mwh"]),
        **request.get("quality_thresholds", {}),
    )
    divergence = assess_shadow_divergence(
        tuple(request["planned_grid_import_mw"]), tuple(request["observed_grid_import_mw"]),
        uncertainty_band_mw=tuple(request["uncertainty_band_mw"]),
        warning_consecutive_intervals=int(request.get("warning_consecutive_intervals", 2)),
        safe_limit_consecutive_intervals=int(request.get("safe_limit_consecutive_intervals", 3)),
        evaluated_at=str(request["generated_at"]),
    )
    snapshot = build_shadow_operations_snapshot(
        str(request["facility_id"]), str(request["generated_at"]),
        str(request["plan_fingerprint"]), quality, divergence,
        required_reduction_mw=float(request["required_reduction_mw"]),
        delivered_reduction_mw=float(request["delivered_reduction_mw"]),
    )
    security = assess_shadow_security(ShadowSecurityControls(**request["security_controls"]))
    blockers = tuple(dict.fromkeys((*snapshot.unresolved_blockers, *security.blockers)))
    payload = {
        "schema_version": SHADOW_VERIFICATION_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(request),
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "read_only": True,
        "ready": not blockers,
        "blockers": list(blockers),
        "snapshot": _serialize(snapshot),
        "security": _serialize(security),
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
