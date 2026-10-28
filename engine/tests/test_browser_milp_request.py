"""Qualify the exact synthetic request emitted by the production browser builder."""
import json
import os
import time
from pathlib import Path

import pytest

from capacity_backtest.application import run_facility_plan
from capacity_backtest.application.facility import parse_facility_plan_request


def browser_request():
    path = os.environ.get("GRIDPULSE_BROWSER_REQUEST")
    if not path:
        pytest.skip("Cross-repository browser fixture supplied only by qualification workflow")
    return json.loads(Path(path).read_text())


@pytest.mark.parametrize("variant", ["default", "no_battery", "no_battery_relaxed", "restricted_flex", "generation"])
def test_browser_default_runs_real_milp_and_replays_within_runtime_budget(variant):
    request = browser_request()
    if variant in {"no_battery", "no_battery_relaxed"}:
        request["batteries"] = []
        if variant == "no_battery_relaxed":
            request["policy"]["operating_target_mw"] = 130
            request["facility"]["import_limit_mw"] = 132
    elif variant == "restricted_flex":
        request["policy"]["maximum_workload_reduction_fraction"] = 0
        request["policy"]["operating_target_mw"] = 130
        request["facility"]["import_limit_mw"] = 132
    elif variant == "generation":
        request["onsite_generation_mw"] = [2.0] * 96
    start = time.monotonic()
    payload = run_facility_plan(request)
    result = payload["result"]
    assert time.monotonic() - start < 90, "Browser mock exceeds hosted execution budget"
    assert result["solver"] == "scipy-highs-milp"
    if variant == "no_battery":
        # At the unchanged 98 MW target the declared flexibility is insufficient.
        # Removing an asset must fail closed, rather than inventing a feasible plan.
        assert result["status"] == "infeasible"
        assert result["assessment"] is None
        assert not result["actions"]
        assert not payload["automatic_live_dispatch_authorized"]
        return
    assert result["status"] in {"optimal", "feasible_not_proven_optimal"}, result["status"]
    assert result["assessment"]["feasible"], result["diagnostics"]
    assert not result["diagnostics"]
    assert len(result["facility"]["points"]) == 96
    assert all(interval["duration_minutes"] == 15 for interval in result["intervals"])
    assert len(result["portfolio"]["workload_trajectories"]) == 5
    assert not payload["automatic_live_dispatch_authorized"]
    if result["status"] == "feasible_not_proven_optimal":
        assert result["optimality_gap"] is not None and result["optimality_gap"] <= .05
    assert result["assessment"]["recovery_complete"]
    assert not result["assessment"]["sla_violations"]
    assert result["assessment"]["battery_terminal_targets_met"]
    if variant == "default" and os.environ.get("GRIDPULSE_BROWSER_JOB_OUTPUT"):
        job = {
            "id": "00000000-0000-4000-8000-000000000001",
            "owner_id": "00000000-0000-4000-8000-000000000002",
            "job_type": "facility_plan", "status": "succeeded",
            "input_payload": request, "input_fingerprint": payload["input_fingerprint"],
            "result_payload": payload, "error": None,
            "created_at": "2026-09-26T00:00:00Z", "started_at": None,
            "completed_at": None, "attempt_count": 1, "lease_owner": None,
            "lease_expires_at": None, "heartbeat_at": None, "checkpoint_payload": {},
            "cancellation_requested": False,
        }
        Path(os.environ["GRIDPULSE_BROWSER_JOB_OUTPUT"]).write_text(json.dumps(job))
    # Keep measurements with the existing qualification reports; no production job is submitted.
    report_dir = Path(os.environ.get("GRIDPULSE_BENCHMARK_DIR", "reports"))
    report_dir.mkdir(parents=True, exist_ok=True)
    metrics = {"variant": variant, "elapsed_seconds": time.monotonic() - start,
               "status": result["status"], "gap": result.get("optimality_gap"),
               "interval_count": len(result["intervals"])}
    if os.name != "nt":
        import resource
        metrics["process_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    (report_dir / f"quarter-hour-{variant}.json").write_text(json.dumps(metrics))


def test_browser_model_preserves_explicit_constraints_and_synthetic_truth():
    inputs = parse_facility_plan_request(browser_request())
    assert inputs["requirement"].truth_class.value == "synthetic_demonstration"
    assert inputs["policy"].solver_time_limit_seconds == 30
    assert inputs["policy"].maximum_variables == 20000
    battery = inputs["batteries"][0]
    battery.validate()
    assert battery.terminal_target_mwh == battery.initial_soc_mwh
    protected = [job for job in inputs["portfolio"].workloads if job.workload_kind.value == "critical_inference"]
    assert len(protected) == 1
    assert protected[0].minimum_power_cap_mw == protected[0].nominal_power_mw
    assert protected[0].maximum_start_delay_minutes == 0
