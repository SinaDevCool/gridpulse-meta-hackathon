"""Bounded counterfactuals over the sole solver and existing physical simulators.

No probabilities, live control or independent physical validation are implied.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from math import isfinite
from typing import Any

from capacity_backtest.data_center.contracts import ScheduledWorkloadAction, WorkloadActionKind
from capacity_backtest.data_center.facility import build_facility_trajectory
from capacity_backtest.data_center.portfolio import evaluate_portfolio
from capacity_backtest.phase2.battery import BatteryRequest, simulate_battery
from capacity_backtest.phase2.thermal_workload import WorkloadConfig, simulate_cooling_workload

from .facility import (
    ENGINE_VERSION,
    _fingerprint,
    _serialize,
    parse_facility_plan_request,
    run_facility_plan,
)

EXPERIMENT_REQUEST_SCHEMA = "gridpulse-facility-experiment-request-v1"
EXPERIMENT_RESULT_SCHEMA = "gridpulse-facility-experiment-result-v1"


def _number(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("experiment values must be finite numbers")
    if value < 0 or (positive and value == 0):
        raise ValueError("experiment value is outside its supported range")
    return float(value)


def changed_request(original: dict, changes: list[dict]) -> dict:
    result = deepcopy(original)
    seen = set()
    for change in changes:
        if set(change) - {"field", "value", "asset_id"} or not {"field", "value"} <= set(change):
            raise ValueError("unsupported change fields")
        field, asset = change["field"], change.get("asset_id")
        if (field, asset) in seen:
            raise ValueError("duplicate experiment change")
        seen.add((field, asset))
        value = _number(
            change["value"],
            positive=field
            not in {
                "initial_soc_fraction",
                "battery_unavailable_interval",
                "workload_availability_delay_minutes",
                "generation_multiplier",
            },
        )
        if field == "import_limit_mw":
            if result["facility"].get("import_limit_profile_mw") is not None:
                raise ValueError(
                    "A connection-envelope experiment needs a separately reviewed interval profile"
                )
            prior = result["facility"]["import_limit_mw"]
            reserve = prior - (result["policy"].get("operating_target_mw") or prior)
            result["facility"]["import_limit_mw"] = value
            if result["policy"].get("operating_target_mw") is not None:
                result["policy"]["operating_target_mw"] = value - reserve
        elif field in {"battery_energy_mwh", "battery_power_mw", "initial_soc_fraction"}:
            batteries = [b for b in result.get("batteries", []) if b["resource_id"] == asset]
            if len(batteries) != 1:
                raise ValueError("select exactly one known battery")
            battery = batteries[0]
            if field == "battery_energy_mwh":
                ratio = value / battery["rated_energy_mwh"]
                for name in (
                    "initial_soc_mwh",
                    "minimum_reserve_mwh",
                    "terminal_target_mwh",
                    "soc_uncertainty_mwh",
                ):
                    if name in battery:
                        battery[name] *= ratio
                battery["rated_energy_mwh"] = value
            elif field == "battery_power_mw":
                battery["rated_power_mw"] = value
            else:
                if value > 1:
                    raise ValueError("SOC fraction must be at most one")
                battery["initial_soc_mwh"] = (
                    value
                    * battery["rated_energy_mwh"]
                    * (1 - battery.get("degradation_fraction", 0))
                )
        elif field == "workload_duration_multiplier":
            jobs = [j for j in result["workloads"] if j["workload_id"] == asset]
            if len(jobs) != 1 or not 0.5 <= value <= 2:
                raise ValueError("select a known workload and a duration multiplier in [0.5, 2]")
            job = jobs[0]
            duration = job["expected_duration_minutes"] * value
            if duration != int(duration):
                raise ValueError("workload duration must resolve to whole minutes")
            job["expected_duration_minutes"] = int(duration)
            if job.get("remaining_work_minutes") is not None:
                job["remaining_work_minutes"] *= value
        elif field == "battery_unavailable_interval":
            batteries = [b for b in result.get("batteries", []) if b["resource_id"] == asset]
            if len(batteries) != 1 or value != int(value) or value >= len(result["intervals"]):
                raise ValueError("select one battery and a valid interval index")
            batteries[0]["unavailable_hours"] = sorted(
                set(batteries[0].get("unavailable_hours", [])) | {int(value)}
            )
        elif field == "workload_availability_delay_minutes":
            from datetime import timedelta

            from capacity_backtest.domain.base import parse_aware_timestamp

            jobs = [j for j in result["workloads"] if j["workload_id"] == asset]
            if len(jobs) != 1 or value != int(value):
                raise ValueError("select one workload and whole delay minutes")
            if jobs[0].get("initially_running"):
                raise ValueError(
                    "running workloads cannot be delayed as an availability experiment"
                )
            jobs[0]["earliest_start"] = (
                parse_aware_timestamp(jobs[0]["earliest_start"], "earliest start")
                + timedelta(minutes=value)
            ).isoformat()
        elif field == "generation_multiplier":
            if not 0.0 <= value <= 2:
                raise ValueError("generation multiplier must be in [0, 2]")
            result["onsite_generation_mw"] = [
                v * value
                for v in result.get("onsite_generation_mw") or [0] * len(result["intervals"])
            ]
        elif field == "cooling_load_multiplier":
            if not 0.5 <= value <= 2:
                raise ValueError("cooling multiplier must be in [0.5, 2]")
            result["facility"]["cooling_load_factor"] *= value
        else:
            raise ValueError("unsupported experiment change")
    return result


def _accepted_baseline(request: dict, baseline: dict) -> None:
    if baseline.get("input_fingerprint") != _fingerprint(request):
        raise ValueError("baseline input fingerprint mismatch")
    if baseline.get("result_fingerprint") != _fingerprint(
        {k: v for k, v in baseline.items() if k != "result_fingerprint"}
    ):
        raise ValueError("baseline result fingerprint mismatch")
    r = baseline.get("result", {})
    if (
        r.get("status") not in {"optimal", "feasible_not_proven_optimal"}
        or r.get("diagnostics")
        or not r.get("assessment", {}).get("feasible")
    ):
        raise ValueError("experiment requires an accepted physical baseline")
    if baseline.get("automatic_live_dispatch_authorized") is not False:
        raise ValueError("only read-only baselines are supported")


def replay_fixed_plan(request: dict, baseline: dict) -> dict:
    inputs = parse_facility_plan_request(request)
    intervals = inputs["intervals"]
    if len({i.duration_minutes for i in intervals}) != 1:
        raise ValueError("mixed replay intervals are not qualified")
    dt = intervals[0].duration_minutes / 60
    result = baseline["result"]
    actions = tuple(
        ScheduledWorkloadAction(
            **{
                **a,
                "action_kind": WorkloadActionKind(a["action_kind"]),
                "assumption_ids": tuple(a.get("assumption_ids", [])),
            }
        )
        for a in result["actions"]
    )
    portfolio = evaluate_portfolio(
        inputs["portfolio"],
        inputs["profiles"],
        intervals,
        actions,
        site_id=inputs["facility"].site_id,
    )
    count = len(intervals)
    raw_requests = result["battery_requests"]
    if len(raw_requests) != len(inputs["batteries"]) * count:
        raise ValueError("frozen battery commands do not match assets and horizon")
    batteries = tuple(
        simulate_battery(
            config,
            [BatteryRequest(**v) for v in raw_requests[index * count : (index + 1) * count]],
            interval_hours=dt,
        )
        for index, config in enumerate(inputs["batteries"])
    )
    adjustment = tuple(result["cooling_adjustment_mw"])
    facility = build_facility_trajectory(
        inputs["facility"],
        intervals,
        portfolio,
        cooling_adjustment_mw=adjustment,
        batteries=batteries,
        onsite_generation_mw=inputs["onsite_generation_mw"],
    )
    thermal = simulate_cooling_workload(
        [max(0, -v) for v in adjustment],
        [max(0, v) for v in adjustment],
        inputs["cooling"],
        WorkloadConfig(0, 0, 24, 0),
        interval_hours=dt,
    )
    violations = []
    prior_work = {t["workload_id"]: t for t in result["portfolio"]["workload_trajectories"]}
    for trajectory in portfolio.workload_trajectories:
        reference = prior_work[trajectory.workload_id]["points"]
        for i, point in enumerate(trajectory.points):
            if point.power_mw > 1e-7 and reference[i]["power_mw"] <= 1e-7:
                violations.append(
                    {
                        "code": "execution_outside_frozen_schedule",
                        "asset_id": trajectory.workload_id,
                        "interval_index": i,
                    }
                )
    targets = (
        inputs["policy"].operating_target_profile_mw
        or (inputs["policy"].operating_target_mw,) * count
    )
    for i, point in enumerate(facility.points):
        for code, magnitude in (
            ("import_limit", point.import_limit_violation_mw),
            (
                "operating_target",
                max(0, point.grid_import_mw - targets[i]) if targets[i] is not None else 0,
            ),
        ):
            if magnitude > 1e-7:
                violations.append(
                    {"code": code, "interval_index": i, "magnitude": magnitude, "unit": "MW"}
                )
    for battery in batteries:
        for i, point in enumerate(battery.points):
            if point.shortfall_mw > 1e-7:
                violations.append(
                    {
                        "code": "battery_command_shortfall",
                        "asset_id": battery.resource_id,
                        "interval_index": i,
                        "magnitude": point.shortfall_mw,
                        "unit": "MW",
                    }
                )
        if not battery.terminal_target_met:
            violations.append(
                {
                    "code": "battery_terminal_target",
                    "asset_id": battery.resource_id,
                    "interval_index": count - 1,
                }
            )
    for trajectory in portfolio.workload_trajectories:
        if not trajectory.deadline_met or trajectory.ending_remaining_work_hours > 1e-7:
            violations.append(
                {
                    "code": "workload_incomplete_or_late",
                    "asset_id": trajectory.workload_id,
                    "interval_index": count - 1,
                }
            )
    for violation in portfolio.sla_violations:
        violations.append(
            {"code": violation.code, "asset_id": violation.workload_id, "interval_index": None}
        )
    for i, point in enumerate(thermal.points):
        if (
            abs(point.cooling_reduction_mw - max(0, -adjustment[i])) > 1e-7
            or abs(point.cooling_rebound_mw - max(0, adjustment[i])) > 1e-7
        ):
            violations.append({"code": "cooling_command_shortfall", "interval_index": i})
    if thermal.ending_thermal_debt_mwh > 1e-7:
        violations.append({"code": "cooling_terminal_debt", "interval_index": count - 1})
    from capacity_backtest.data_center.assessment import assess_facility_flexibility
    from capacity_backtest.data_center.facility import FacilityPowerPoint, FacilityPowerTrajectory

    raw_baseline = result["baseline_facility"]
    reference = FacilityPowerTrajectory(
        raw_baseline["facility_id"],
        tuple(FacilityPowerPoint(**p) for p in raw_baseline["points"]),
        (),
        raw_baseline["maximum_grid_import_mw"],
        raw_baseline["import_limit_violation_count"],
    )
    assessment = assess_facility_flexibility(
        inputs["requirement"],
        intervals,
        reference,
        facility,
        portfolio,
        None,
        event_intervals=inputs["policy"].event_intervals,
        batteries=batteries,
        cooling_recovery_complete=thermal.ending_thermal_debt_mwh <= 1e-7,
        replayed_rebound_mw=max(
            (
                max(0, actual.grid_import_mw - base.grid_import_mw)
                for actual, base, event in zip(
                    facility.points, reference.points, inputs["policy"].event_intervals
                )
                if not event
            ),
            default=0,
        ),
    )
    for code in assessment.blockers:
        violations.append({"code": code, "interval_index": None})
    if inputs["fatigue_limits"] is not None:
        from capacity_backtest.phase2.fatigue import evaluate_fatigue

        fatigue = evaluate_fatigue(
            [
                max(0, base.grid_import_mw - actual.grid_import_mw)
                for base, actual in zip(reference.points, facility.points)
            ],
            sum(b.equivalent_full_cycles for b in batteries),
            inputs["fatigue_limits"],
            interval_hours=dt,
        )
        violations.extend({"code": code, "interval_index": None} for code in fatigue.violations)
    return {
        "accepted": not violations,
        "violations": violations,
        "first_violation_index": min(
            (v["interval_index"] for v in violations if v["interval_index"] is not None),
            default=None,
        ),
        "peak_import_mw": facility.maximum_grid_import_mw,
        "above_import_limit_minutes": sum(
            intervals[p.interval_index].duration_minutes
            for p in facility.points
            if p.import_limit_violation_mw > 1e-7
        ),
        "remaining_work_hours": sum(
            t.ending_remaining_work_hours for t in portfolio.workload_trajectories
        ),
        "facility": _serialize(facility),
        "portfolio": _serialize(portfolio),
        "batteries": _serialize(batteries),
        "ending_thermal_debt_mwh": thermal.ending_thermal_debt_mwh,
        "unsupported_checks": [
            "rack_temperature",
            "subinterval_ramps",
            "independent_measurement_validation",
        ],
    }


def comparison_metrics(
    request: dict,
    facility: dict,
    portfolio: dict,
    batteries: list | tuple,
    assessment: dict | None = None,
) -> dict:
    """Common replay-derived comparison evidence. No marginal/causal inference."""
    durations = [row["duration_minutes"] / 60 for row in request["intervals"]]
    points = facility["points"]
    if len(points) != len(durations):
        raise ValueError("comparison trajectory does not match the submitted horizon")
    target = request["policy"].get("operating_target_mw")
    targets = request["policy"].get("operating_target_profile_mw") or [target] * len(points)
    configs = {b["resource_id"]: b for b in request.get("batteries", [])}
    soc_fractions = []
    for trajectory in batteries:
        config = configs[trajectory["resource_id"]]
        capacity = config["rated_energy_mwh"] * (1 - config.get("degradation_fraction", 0))
        soc_fractions.extend(
            [config["initial_soc_mwh"] / capacity]
            + [p["soc_mwh"] / capacity for p in trajectory["points"]]
        )
    return {
        "grid_import_mwh": sum(p["grid_import_mw"] * dt for p, dt in zip(points, durations)),
        "above_target_minutes": None
        if all(t is None for t in targets)
        else sum(
            dt * 60
            for p, dt, t in zip(points, durations, targets)
            if t is not None and p["grid_import_mw"] > t + 1e-7
        ),
        "minimum_soc_fraction": min(soc_fractions, default=None),
        "battery_delivered_mwh": sum(b["delivered_mwh"] for b in batteries),
        "battery_equivalent_full_cycles": sum(b["equivalent_full_cycles"] for b in batteries),
        "terminal_target_met": all(b["terminal_target_met"] for b in batteries)
        if batteries
        else None,
        "deadline_checks_met": sum(
            bool(t["deadline_met"]) for t in portfolio["workload_trajectories"]
        ),
        "workload_count": len(portfolio["workload_trajectories"]),
        "rebound_peak_mw": assessment.get("rebound_peak_mw") if assessment else None,
        "basis": "canonical_physical_replay",
        "causal_binding_constraints_assessed": False,
    }


def run_facility_experiment(
    request: dict, *, checkpoint: Callable[[], None] = lambda: None
) -> dict:
    if request.get("schema_version") != EXPERIMENT_REQUEST_SCHEMA or set(request) - {
        "schema_version",
        "facility_plan",
        "baseline",
        "cases",
    }:
        raise ValueError("unsupported experiment request")
    original, baseline, cases = request["facility_plan"], request["baseline"], request["cases"]
    _accepted_baseline(original, baseline)
    if (
        not isinstance(cases, list)
        or not 1 <= len(cases) <= 4
        or len({c["case_id"] for c in cases}) != len(cases)
    ):
        raise ValueError("experiments require 1 to 4 unique cases")
    outcomes = []
    # All cases are validated before any expensive work begins.
    prepared = []
    for case in cases:
        if set(case) != {"case_id", "mode", "changes"} or case["mode"] not in {
            "alternative",
            "frozen_plan",
        }:
            raise ValueError("unsupported experiment case")
        if not isinstance(case["changes"], list) or not 1 <= len(case["changes"]) <= 4:
            raise ValueError("cases require 1 to 4 explicit changes")
        changed = changed_request(original, case["changes"])
        inputs = parse_facility_plan_request(changed)
        if (
            len(inputs["intervals"]) > 100
            or len(inputs["portfolio"].workloads) > 5
            or len(inputs["batteries"]) > 1
        ):
            raise ValueError("experiment exceeds qualified scale")
        if not 0 < inputs["policy"].solver_time_limit_seconds <= 30:
            raise ValueError("experiment solve limit must be at most 30 seconds")
        prepared.append((case, changed))
    for case, changed in prepared:
        checkpoint()
        outcome = {
            "case_id": case["case_id"],
            "mode": case["mode"],
            "changes": case["changes"],
            "input_fingerprint": _fingerprint(changed),
        }
        try:
            if case["mode"] == "alternative":
                plan = run_facility_plan(changed)
                outcome.update(
                    {
                        "status": "completed",
                        "plan": plan,
                        "accepted": (
                            plan["result"]["status"] in {"optimal", "feasible_not_proven_optimal"}
                            and bool(plan["result"].get("assessment", {}).get("feasible"))
                            and not plan["result"].get("diagnostics")
                        ),
                    }
                )
                if outcome["accepted"]:
                    solved = plan["result"]
                    trajectory = solved["facility"]
                    outcome["metrics"] = comparison_metrics(
                        changed,
                        trajectory,
                        solved["portfolio"],
                        solved["battery_trajectories"],
                        solved["assessment"],
                    )
                    outcome["solver"] = {
                        key: solved.get(key)
                        for key in (
                            "status",
                            "solver_termination",
                            "optimality_gap",
                            "objective_bound_eur",
                            "objective_eur",
                        )
                    }
                    violations = [
                        p for p in trajectory["points"] if p["import_limit_violation_mw"] > 1e-7
                    ]
                    outcome.update(
                        {
                            "peak_import_mw": trajectory["maximum_grid_import_mw"],
                            "above_import_limit_minutes": sum(
                                changed["intervals"][p["interval_index"]]["duration_minutes"]
                                for p in violations
                            ),
                            "remaining_work_hours": sum(
                                t["ending_remaining_work_hours"]
                                for t in solved["portfolio"]["workload_trajectories"]
                            ),
                            "first_violation_index": min(
                                (p["interval_index"] for p in violations), default=None
                            ),
                        }
                    )
            else:
                outcome.update({"status": "completed", **replay_fixed_plan(changed, baseline)})
                outcome["metrics"] = comparison_metrics(
                    changed, outcome["facility"], outcome["portfolio"], outcome["batteries"]
                )
        except (ValueError, TypeError) as error:
            outcome.update(
                {"status": "unsupported_or_invalid", "accepted": False, "reason": str(error)}
            )
        outcomes.append(outcome)
        checkpoint()
    payload = {
        "schema_version": EXPERIMENT_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(request),
        "baseline_result_fingerprint": baseline["result_fingerprint"],
        "baseline_metrics": comparison_metrics(
            original,
            baseline["result"]["facility"],
            baseline["result"]["portfolio"],
            baseline["result"]["battery_trajectories"],
            baseline["result"]["assessment"],
        ),
        "cases": outcomes,
        "scenario_basis": "assumed_not_calibrated_probability",
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
