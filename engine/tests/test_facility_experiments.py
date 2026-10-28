from copy import deepcopy

import pytest

from capacity_backtest.application.experiments import changed_request, run_facility_experiment
from capacity_backtest.application.facility import run_facility_plan

from .test_application_facility import request


def fixture():
    plan = request()
    plan["policy"]["solver_time_limit_seconds"] = 5
    baseline = run_facility_plan(plan)
    return {"schema_version": "gridpulse-facility-experiment-request-v1", "facility_plan": plan,
            "baseline": baseline, "cases": [{"case_id": "lower-limit", "mode": "frozen_plan",
            "changes": [{"field": "import_limit_mw", "value": 0.001}]}]}


def test_fixed_plan_reports_breaches_without_altering_baseline():
    payload = fixture()
    before = deepcopy(payload)
    result = run_facility_experiment(payload)
    case = result["cases"][0]
    assert case["status"] == "completed"
    assert not case["accepted"] and case["above_import_limit_minutes"] > 0
    assert case["first_violation_index"] is not None
    assert payload == before
    assert not result["automatic_live_dispatch_authorized"]


def test_alternative_calls_canonical_solver_and_retains_lineage():
    payload = fixture()
    payload["cases"][0]["mode"] = "alternative"
    payload["cases"][0]["changes"][0]["value"] = 0.5
    result = run_facility_experiment(payload)
    assert result["cases"][0]["plan"]["engine_version"] == result["engine_version"]
    assert result["baseline_result_fingerprint"] == payload["baseline"]["result_fingerprint"]
    case = result["cases"][0]
    assert case["accepted"]
    assert case["peak_import_mw"] == case["plan"]["result"]["facility"]["maximum_grid_import_mw"]
    assert case["remaining_work_hours"] == 0


def test_tampered_or_cross_input_baseline_fails_before_solve():
    payload = fixture()
    payload["baseline"]["result"]["status"] = "infeasible"
    with pytest.raises(ValueError, match="fingerprint"):
        run_facility_experiment(payload)


def test_budget_unknown_changes_and_nonfinite_values_fail_closed():
    payload = fixture()
    payload["cases"] *= 5
    with pytest.raises(ValueError, match="unique cases"):
        run_facility_experiment(payload)
    for value in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="finite"):
            changed_request(request(), [{"field": "import_limit_mw", "value": value}])


def test_workload_extension_is_not_silently_accepted_as_frozen():
    payload = fixture()
    job = payload["facility_plan"]["workloads"][0]["workload_id"]
    payload["cases"][0]["changes"] = [{"field": "workload_duration_multiplier", "asset_id": job, "value": 2}]
    outcome = run_facility_experiment(payload)["cases"][0]
    assert not outcome["accepted"]


def test_common_metrics_use_interval_energy_and_replay_lineage():
    payload = fixture()
    payload["cases"][0]["changes"][0]["value"] = payload["facility_plan"]["facility"]["import_limit_mw"]
    result = run_facility_experiment(payload)
    metrics = result["cases"][0]["metrics"]
    assert metrics["basis"] == "canonical_physical_replay"
    assert metrics["grid_import_mwh"] == pytest.approx(result["baseline_metrics"]["grid_import_mwh"])
    assert metrics["causal_binding_constraints_assessed"] is False
    assert metrics["deadline_checks_met"] == metrics["workload_count"]
