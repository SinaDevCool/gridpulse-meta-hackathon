"""Versioned transport boundary for canonical facility uncertainty analysis."""

from __future__ import annotations

from typing import Any

from capacity_backtest.data_center.uncertainty import (
    ScenarioBounds,
    evaluate_uncertain_flexibility,
    generate_uncertainty_scenarios,
)
from capacity_backtest.phase1.risk import RiskPolicy

from .facility import ENGINE_VERSION, _fingerprint, _serialize, parse_facility_plan_request

UNCERTAINTY_REQUEST_SCHEMA = "gridpulse-facility-uncertainty-request-v1"
UNCERTAINTY_RESULT_SCHEMA = "gridpulse-facility-uncertainty-application-result-v1"


def run_facility_uncertainty(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != UNCERTAINTY_REQUEST_SCHEMA:
        raise ValueError("unsupported facility-uncertainty request schema")
    plan_request = request.get("facility_plan")
    if not isinstance(plan_request, dict):
        raise TypeError("facility_plan must contain a canonical facility-plan request")
    inputs = parse_facility_plan_request(plan_request)
    scenarios = generate_uncertainty_scenarios(
        ScenarioBounds(**request["bounds"]),
        horizon_size=len(inputs["intervals"]),
        count=int(request["scenario_count"]),
        seed=int(request["seed"]),
    )
    method = request.get("evaluation_method", "independent_scenario_benchmark")
    if method not in {"independent_scenario_benchmark", "common_command_scenario_milp"}:
        raise ValueError("unsupported uncertainty evaluation method")
    if method == "common_command_scenario_milp":
        from capacity_backtest.data_center.common_plan import optimize_common_plan
        result = optimize_common_plan(inputs, scenarios)
    else:
        result = evaluate_uncertain_flexibility(
        **inputs,
        scenarios=scenarios,
        risk_policy=RiskPolicy(str(request.get("risk_policy", "chance_constrained"))),
        confidence=float(request.get("confidence", 0.9)),
    )
    payload = {
        "schema_version": UNCERTAINTY_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(request),
        "truth_class": inputs["requirement"].truth_class.value,
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "result": _serialize(result),
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
