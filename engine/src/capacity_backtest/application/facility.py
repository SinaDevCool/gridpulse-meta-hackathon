"""Versioned dictionary boundary for the canonical facility planner."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from importlib.metadata import version
from typing import Any

from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.contracts import (
    AIWorkload,
    FacilityOptimizationPolicy,
    FlexibilityEconomics,
    PlanningInterval,
    WorkloadKind,
    WorkloadSLA,
)
from capacity_backtest.data_center.facility import FacilityConfig
from capacity_backtest.data_center.optimizer import optimize_facility_flexibility
from capacity_backtest.data_center.portfolio import WorkloadPortfolio
from capacity_backtest.data_center.power_profiles import (
    PiecewiseLinearPowerProfile,
    PowerThroughputPoint,
)
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase2.battery import BatteryConfig
from capacity_backtest.phase2.fatigue import FatigueLimits
from capacity_backtest.phase2.thermal_workload import CoolingConfig

from .transport_schema import FACILITY_PLAN_OPTIONAL, FACILITY_PLAN_REQUIRED

FACILITY_PLAN_REQUEST_SCHEMA = "gridpulse-facility-plan-request-v1"
FACILITY_PLAN_RESULT_SCHEMA = "gridpulse-facility-plan-application-result-v1"
ENGINE_VERSION = f"gridpulse-capacity-backtest-{version('gridpulse-capacity-backtest')}"


def _truth(value: object) -> TruthClass:
    return value if isinstance(value, TruthClass) else TruthClass(str(value))


def _serialize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _serialize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    return value


def _fingerprint(value: object) -> str:
    encoded = json.dumps(_serialize(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_keys(value: dict[str, Any], keys: set[str], name: str) -> None:
    missing = keys - value.keys()
    if missing:
        raise ValueError(f"{name} is missing required fields: {', '.join(sorted(missing))}")


def _requirement(row: dict[str, Any]) -> FlexibilityRequirement:
    values = dict(row)
    values["truth_class"] = _truth(values["truth_class"])
    values["assumption_ids"] = tuple(values.get("assumption_ids", ()))
    values["blockers"] = tuple(values.get("blockers", ()))
    result = FlexibilityRequirement(**values)
    result.validate()
    return result


def _workload(row: dict[str, Any]) -> AIWorkload:
    values = dict(row)
    values["workload_kind"] = WorkloadKind(values["workload_kind"])
    values["truth_class"] = _truth(values["truth_class"])
    values["allowed_site_ids"] = tuple(values["allowed_site_ids"])
    values["data_residency_regions"] = tuple(values["data_residency_regions"])
    values["assumption_ids"] = tuple(values.get("assumption_ids", ()))
    values["sla"] = WorkloadSLA(**values["sla"])
    result = AIWorkload(**values)
    result.validate()
    return result


def _profile(row: dict[str, Any]) -> PiecewiseLinearPowerProfile:
    values = dict(row)
    values["truth_class"] = _truth(values["truth_class"])
    values["points"] = tuple(PowerThroughputPoint(**point) for point in values["points"])
    result = PiecewiseLinearPowerProfile(**values)
    result.validate()
    return result


def parse_facility_plan_request(request: dict[str, Any]) -> dict[str, Any]:
    """Parse the shared facility request once for every application-level analysis."""
    if request.get("schema_version") != FACILITY_PLAN_REQUEST_SCHEMA:
        raise ValueError("unsupported facility-plan request schema")
    _require_keys(
        request,
        set(FACILITY_PLAN_REQUIRED),
        "facility-plan request",
    )
    allowed = FACILITY_PLAN_REQUIRED | FACILITY_PLAN_OPTIONAL
    unknown = request.keys() - allowed
    if unknown:
        raise ValueError(f"unsupported facility-plan fields: {', '.join(sorted(unknown))}")
    intervals = tuple(PlanningInterval(**row) for row in request["intervals"])
    requirement = _requirement(request["requirement"])
    facility_values = dict(request["facility"])
    facility_values["truth_class"] = _truth(facility_values["truth_class"])
    if facility_values.get("import_limit_profile_mw") is not None:
        facility_values["import_limit_profile_mw"] = tuple(
            facility_values["import_limit_profile_mw"]
        )
    facility = FacilityConfig(**facility_values)
    workloads = tuple(_workload(row) for row in request["workloads"])
    parsed_profiles = tuple(map(_profile, request["profiles"]))
    profiles = {profile.workload_id: profile for profile in parsed_profiles}
    if len(profiles) != len(parsed_profiles):
        raise ValueError("duplicate workload profile identities")
    policy_values = dict(request["policy"])
    policy_values["event_intervals"] = tuple(policy_values["event_intervals"])
    policy_values["battery_temperature_c"] = tuple(policy_values["battery_temperature_c"])
    if policy_values.get("operating_target_profile_mw") is not None:
        policy_values["operating_target_profile_mw"] = tuple(
            policy_values["operating_target_profile_mw"]
        )
    policy = FacilityOptimizationPolicy(**policy_values)
    economics_values = dict(request["economics"])
    economics_values["import_price_eur_per_mwh"] = tuple(
        economics_values["import_price_eur_per_mwh"]
    )
    economics = FlexibilityEconomics(**economics_values)
    cooling = CoolingConfig(**request["cooling"])
    return {
        "requirement": requirement,
        "intervals": intervals,
        "facility": facility,
        "portfolio": WorkloadPortfolio(
            str(request.get("portfolio_id", "portfolio")),
            workloads,
            fleet_gpu_capacity=request.get("fleet_gpu_capacity"),
            idle_gpu_power_watts=request.get("idle_gpu_power_watts", 0.0),
        ),
        "profiles": profiles,
        "policy": policy,
        "economics": economics,
        "cooling": cooling,
        "batteries": tuple(
            BatteryConfig(
                **{
                    **row,
                    "unavailable_hours": tuple(row.get("unavailable_hours", ())),
                    "unavailable_at": tuple(row.get("unavailable_at", ())),
                }
            )
            for row in request.get("batteries", ())
        ),
        "onsite_generation_mw": (
            tuple(request["onsite_generation_mw"])
            if request.get("onsite_generation_mw") is not None
            else None
        ),
        "fatigue_limits": (
            FatigueLimits(**request["fatigue_limits"])
            if request.get("fatigue_limits") is not None
            else None
        ),
    }


def run_facility_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Validate a transport request, invoke the sole optimizer, and return an immutable result."""
    inputs = parse_facility_plan_request(request)
    result = optimize_facility_flexibility(**inputs)
    from capacity_backtest.data_center.plan_evidence import plan_evidence

    requirement = inputs["requirement"]
    input_fingerprint = _fingerprint(request)
    payload = {
        "schema_version": FACILITY_PLAN_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": input_fingerprint,
        "truth_class": requirement.truth_class.value,
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "result": _serialize(result),
        "diagnostic_evidence": plan_evidence(inputs, result),
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
