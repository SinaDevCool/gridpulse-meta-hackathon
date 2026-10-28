"""Versioned cutoff-safe rolling-planning application boundary."""

from __future__ import annotations

from typing import Any

from capacity_backtest.data_center.rolling_planner import (
    RollingPlanningWindow,
    run_rolling_planner,
)
from capacity_backtest.data_center.uncertainty import UncertaintyScenario

from .facility import ENGINE_VERSION, _fingerprint, _serialize, parse_facility_plan_request

ROLLING_PLAN_REQUEST_SCHEMA = "gridpulse-rolling-facility-plan-request-v1"
ROLLING_PLAN_RESULT_SCHEMA = "gridpulse-rolling-facility-plan-application-result-v1"
CHRONOLOGICAL_SHADOW_REQUEST_SCHEMA = "gridpulse-chronological-shadow-request-v1"
CHRONOLOGICAL_SHADOW_RESULT_SCHEMA = "gridpulse-chronological-shadow-result-v1"


def run_rolling_facility_plan(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != ROLLING_PLAN_REQUEST_SCHEMA:
        raise ValueError("unsupported rolling-facility-plan request schema")
    plan_request = request.get("facility_plan")
    if not isinstance(plan_request, dict):
        raise TypeError("facility_plan must contain a canonical facility-plan request")
    inputs = parse_facility_plan_request(plan_request)
    windows = tuple(
        RollingPlanningWindow(
            window_id=str(row["window_id"]),
            cutoff=str(row["cutoff"]),
            forecast_fingerprint=str(row["forecast_fingerprint"]),
            scenarios=tuple(
                UncertaintyScenario(
                    scenario_id=str(item["scenario_id"]),
                    probability=float(item["probability"]),
                    battery_temperature_c=tuple(item["battery_temperature_c"]),
                    onsite_generation_mw=tuple(item["onsite_generation_mw"]),
                    assumption_ids=tuple(item.get("assumption_ids", ())),
                )
                for item in row["scenarios"]
            ),
            recalculation_reason=str(row["recalculation_reason"]),
        )
        for row in request["windows"]
    )
    result = run_rolling_planner(
        windows=windows,
        **inputs,
        confidence=float(request.get("confidence", 0.9)),
    )
    payload = {
        "schema_version": ROLLING_PLAN_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(request),
        "truth_class": inputs["requirement"].truth_class.value,
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "result": _serialize(result),
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload



def run_chronological_shadow(request: dict[str, Any]) -> dict[str, Any]:
    """Replan unexecuted suffixes; executed decisions and state remain immutable.

    Checkpoint overhead, remaining work and pause counters are carried from the
    canonical replay; migration boundaries remain unsupported.
    """
    from copy import deepcopy

    from capacity_backtest.domain.base import parse_aware_timestamp

    from .experiments import changed_request
    from .facility import run_facility_plan

    if request.get("schema_version") != CHRONOLOGICAL_SHADOW_REQUEST_SCHEMA:
        raise ValueError("unsupported chronological-shadow request")
    original = deepcopy(request["facility_plan"])
    windows = request["windows"]
    if not isinstance(windows, list) or not 1 <= len(windows) <= 4:
        raise ValueError("shadow replay requires 1 to 4 windows")
    for window in windows:
        if set(window) - {"cutoff", "available_at", "changes"} or not {"cutoff", "available_at"} <= set(window):
            raise ValueError("unsupported shadow window fields")
        if not isinstance(window.get("changes", []), list) or len(window.get("changes", [])) > 4:
            raise ValueError("shadow windows allow at most four changes")
        if parse_aware_timestamp(window["available_at"], "available_at") > parse_aware_timestamp(window["cutoff"], "cutoff"):
            raise ValueError("future forecast leaked across planning cutoff")
    starts = [v["start"] for v in original["intervals"]]
    indexes = [starts.index(w["cutoff"]) for w in windows]
    if indexes != sorted(set(indexes)) or indexes[0] != 0:
        raise ValueError("shadow windows must start at horizon start and advance chronologically")
    duration = original["intervals"][0]["duration_minutes"]
    if any(v["duration_minutes"] != duration for v in original["intervals"]):
        raise ValueError("mixed shadow intervals are not qualified")
    if len(starts) > 96 or len(original["workloads"]) > 5 or len(original.get("batteries", [])) > 1:
        raise ValueError("shadow horizon exceeds qualification budget")
    if not 0 < original["policy"]["solver_time_limit_seconds"] <= 30:
        raise ValueError("shadow solve limit must be at most 30 seconds")
    previous = None
    previous_start = 0
    active = deepcopy(original)
    revisions = []
    completed = set()
    executed_reductions: list[float] = []
    executed_cycles = 0.0
    reference = None
    for window, start in zip(windows, indexes):
        cutoff = parse_aware_timestamp(window["cutoff"], "cutoff")
        if parse_aware_timestamp(window["available_at"], "available_at") > cutoff:
            raise ValueError("future forecast leaked across planning cutoff")
        stop = start - previous_start
        if previous is not None:
            r = previous["result"]
            if r["status"] not in {"optimal", "feasible_not_proven_optimal"}:
                break
            executed_reductions.extend(max(0, reference[previous_start + i]["grid_import_mw"] - p["grid_import_mw"])
                                       for i, p in enumerate(r["facility"]["points"][:stop]))
            for i, battery in enumerate(active.get("batteries", [])):
                trajectory = r["battery_trajectories"][i]
                capacity = battery["rated_energy_mwh"] * (1 - battery.get("degradation_fraction", 0)) * battery.get("maximum_soc_fraction", 1)
                executed_cycles += sum(abs(p["delivered_power_mw"]) * duration / 60 for p in trajectory["points"][:stop]) / (2 * capacity)
                battery["initial_soc_mwh"] = trajectory["points"][stop - 1]["soc_mwh"]
                battery["initial_power_mw"] = trajectory["points"][stop - 1]["delivered_power_mw"]
                commands = r["battery_requests"][i * len(active["intervals"]): (i + 1) * len(active["intervals"])]
                modes = [c.get("operating_mode") or ("discharge" if c["power_mw"] > 0 else "charge" if c["power_mw"] < 0 else "idle") for c in commands[:stop]]
                mode = modes[-1]
                count = 0
                for item in reversed(modes):
                    if item != mode:
                        break
                    count += 1
                battery["initial_mode_minutes"] = count * duration + (battery.get("initial_mode_minutes", 0) if count == stop and battery.get("initial_mode") == mode else 0)
                battery["initial_mode"] = mode
                battery["unavailable_hours"] = [j - stop for j in battery.get("unavailable_hours", []) if j >= stop]
            trajectories = {t["workload_id"]: t for t in r["portfolio"]["workload_trajectories"]}
            pending = []
            for job in active["workloads"]:
                trajectory = trajectories[job["workload_id"]]
                point = trajectory["points"][stop - 1]
                if point["remaining_work_hours"] <= 1e-9:
                    completed.add(job["workload_id"])
                    continue
                if point["status"] == "moved" or point.get("movement_count", 0):
                    raise ValueError("migration boundary state is not qualified for shadow replanning")
                job["initial_execution_state"] = point["status"] if point["status"] in {"paused", "checkpointing", "restarting"} else None
                job["initial_overhead_remaining_minutes"] = point.get("overhead_remaining_minutes", 0)
                job["initial_pause_count"] = point.get("pause_count", 0)
                job["initial_movement_count"] = point.get("movement_count", 0)
                job["remaining_work_minutes"] = point["remaining_work_hours"] * 60
                job["initially_running"] = point["status"] == "running"
                # Keep original earliest_start: maximum delay remains tied to the original permission.
                pending.append(job)
            active["workloads"] = pending
            active["profiles"] = [p for p in active["profiles"] if p["workload_id"] not in completed]
            debt = active["cooling"].get("initial_thermal_debt_mwh", 0)
            for adjustment in r["cooling_adjustment_mw"][:stop]:
                debt += max(0, -adjustment) * duration / 60
                debt -= max(0, adjustment) * active["cooling"].get("recovery_efficiency", 1) * duration / 60
            active["cooling"]["initial_thermal_debt_mwh"] = max(0, debt)
            active["intervals"] = [{**v, "index": i} for i, v in enumerate(active["intervals"][stop:])]
            for key in ("event_intervals", "battery_temperature_c"):
                active["policy"][key] = active["policy"][key][stop:]
            active["economics"]["import_price_eur_per_mwh"] = active["economics"]["import_price_eur_per_mwh"][stop:]
            if active.get("onsite_generation_mw") is not None:
                active["onsite_generation_mw"] = active["onsite_generation_mw"][stop:]
        active = changed_request(active, window.get("changes", []))
        if not any(active["policy"]["event_intervals"]):
            # The event has elapsed. Continue physical and terminal recovery;
            # do not invent a new event or demand another event reduction.
            active["requirement"]["requested_import_mw"] = active["requirement"]["firm_limit_mw"]
            active["requirement"]["surplus_capacity_mw"] = max(0, active["requirement"]["conditional_limit_mw"] - active["requirement"]["requested_import_mw"])
            active["requirement"]["required_reduction_mw"] = 0
            active["requirement"]["conservative_required_reduction_mw"] = 0
        state = {"batteries": deepcopy(active.get("batteries", [])), "workloads": deepcopy(active["workloads"]), "cooling": deepcopy(active["cooling"])}
        plan = run_facility_plan(active)
        if reference is None and plan["result"].get("baseline_facility"):
            reference = deepcopy(plan["result"]["baseline_facility"]["points"])
        cumulative_fatigue = None
        shadow_accepted = plan["result"]["status"] in {"optimal", "feasible_not_proven_optimal"}
        if shadow_accepted and active.get("fatigue_limits") is not None:
            from capacity_backtest.phase2.fatigue import FatigueLimits, evaluate_fatigue
            future = [max(0, reference[start + i]["grid_import_mw"] - p["grid_import_mw"])
                      for i, p in enumerate(plan["result"]["facility"]["points"])]
            cycles = executed_cycles + sum(b["equivalent_full_cycles"] for b in plan["result"]["battery_trajectories"])
            cumulative_fatigue = _serialize(evaluate_fatigue(executed_reductions + future, cycles,
                FatigueLimits(**active["fatigue_limits"]), interval_hours=duration / 60))
            shadow_accepted = cumulative_fatigue["passed"]
        revisions.append({"cutoff": window["cutoff"], "available_at": window["available_at"],
                          "input_fingerprint": _fingerprint(active), "initial_state": state,
                          "completed_workload_ids": sorted(completed), "plan": plan,
                          "accepted": shadow_accepted, "cumulative_fatigue": cumulative_fatigue,
                          "remaining_battery_horizon_assessed": plan["result"]["status"] in {"optimal", "feasible_not_proven_optimal"}})
        if not shadow_accepted:
            break
        previous, previous_start = plan, start
    payload = {"schema_version": CHRONOLOGICAL_SHADOW_RESULT_SCHEMA, "engine_version": ENGINE_VERSION,
               "input_fingerprint": _fingerprint(request), "revisions": revisions, "automatic_live_dispatch_authorized": False,
               "state_source": "model_replay_not_measured",
               "limitations": ["migration carryover is not qualified", "forecasts are assumed inputs, not measured disturbances"], "fallback_policy": "stop_on_failure_no_stale_plan"}
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
