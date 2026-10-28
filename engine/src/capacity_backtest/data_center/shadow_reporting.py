"""Canonical shadow operations snapshots and reports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .shadow_monitor import ShadowDivergenceAssessment
from .telemetry_quality import TelemetryQualityAssessment


@dataclass(frozen=True)
class ShadowOperationsSnapshot:
    facility_id: str
    generated_at: str
    plan_fingerprint: str
    telemetry: TelemetryQualityAssessment
    divergence: ShadowDivergenceAssessment
    required_reduction_mw: float
    delivered_reduction_mw: float
    unresolved_blockers: tuple[str, ...]
    fingerprint: str
    automatic_live_dispatch_authorized: bool = False
    schema_version: str = "gridpulse-shadow-operations-snapshot-v1"


def build_shadow_operations_snapshot(
    facility_id: str,
    generated_at: str,
    plan_fingerprint: str,
    telemetry: TelemetryQualityAssessment,
    divergence: ShadowDivergenceAssessment,
    *,
    required_reduction_mw: float,
    delivered_reduction_mw: float,
) -> ShadowOperationsSnapshot:
    if not facility_id or len(plan_fingerprint) != 64 or min(required_reduction_mw, delivered_reduction_mw) < 0:
        raise ValueError("shadow snapshot identity or powers are invalid")
    blockers = tuple(dict.fromkeys((*telemetry.blockers, *divergence.blockers)))
    payload = {
        "facility_id": facility_id, "generated_at": generated_at,
        "plan_fingerprint": plan_fingerprint, "telemetry": asdict(telemetry),
        "divergence": asdict(divergence), "required": required_reduction_mw,
        "delivered": delivered_reduction_mw,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return ShadowOperationsSnapshot(
        facility_id, generated_at, plan_fingerprint, telemetry, divergence,
        required_reduction_mw, delivered_reduction_mw, blockers, fingerprint,
    )
