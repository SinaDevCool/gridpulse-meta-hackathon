"""Chronological linear DeFlex optimization against synthetic AC envelopes."""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.optimize import linprog  # type: ignore[import-untyped]
from scipy.sparse import lil_matrix  # type: ignore[import-untyped]

from grid_data.deflex import FlexibilityPolicy

from .storage import atomic_write

if TYPE_CHECKING:
    from .backtest import BenchmarkRecord

VARIABLES = (
    "grid",
    "charge",
    "discharge",
    "shift",
    "recovery",
    "critical_unserved",
    "flexible_unserved",
    "soc",
)


def optimize_flexibility(
    demand_mw: list[float],
    n0_envelope_mw: list[float],
    n1_envelope_mw: list[float],
    policy: FlexibilityPolicy,
) -> dict[str, Any]:
    policy.validate()
    hours = len(demand_mw)
    if not hours or len(n0_envelope_mw) != hours or len(n1_envelope_mw) != hours:
        raise ValueError("optimization inputs must be non-empty and aligned")
    width = len(VARIABLES)
    def index(hour: int, variable: str) -> int:
        return hour * width + VARIABLES.index(variable)
    objective = np.zeros(hours * width)
    bounds = []
    reserve = policy.battery_energy_mwh * policy.minimum_reserve_soc_fraction
    initial_soc = policy.battery_energy_mwh
    for hour, demand in enumerate(demand_mw):
        flexible = demand * (1 - policy.critical_load_fraction)
        shift_limit = min(flexible, demand * policy.interruptible_fraction)
        envelope = max(0.0, min(n0_envelope_mw[hour], n1_envelope_mw[hour]))
        bounds.extend(
            [
                (0, envelope),
                (0, policy.battery_power_mw),
                (0, policy.battery_power_mw),
                (0, shift_limit),
                (0, flexible),
                (0, demand * policy.critical_load_fraction),
                (0, flexible),
                (reserve, policy.battery_energy_mwh),
            ]
        )
        objective[index(hour, "charge")] = 1 + policy.battery_degradation_cost_per_mwh
        objective[index(hour, "discharge")] = 1 + policy.battery_degradation_cost_per_mwh
        objective[index(hour, "shift")] = 100
        objective[index(hour, "critical_unserved")] = 1_000_000
        objective[index(hour, "flexible_unserved")] = 100_000
    equality = lil_matrix((hours * 2 + 1, hours * width))
    equality_rhs = np.zeros(hours * 2 + 1)
    for hour, demand in enumerate(demand_mw):
        for variable, coefficient in {
            "grid": 1,
            "discharge": 1,
            "critical_unserved": 1,
            "flexible_unserved": 1,
            "shift": 1,
            "recovery": -1,
            "charge": -1,
        }.items():
            equality[hour, index(hour, variable)] = coefficient
        equality_rhs[hour] = demand - policy.backup_generation_mw
        soc_row = hours + hour
        equality[soc_row, index(hour, "soc")] = 1
        equality[soc_row, index(hour, "charge")] = -policy.charge_efficiency
        equality[soc_row, index(hour, "discharge")] = 1 / policy.discharge_efficiency
        if hour:
            equality[soc_row, index(hour - 1, "soc")] = -1
        else:
            equality_rhs[soc_row] = initial_soc
    # All shifted work must be recovered by the horizon.
    terminal_row = hours * 2
    for hour in range(hours):
        equality[terminal_row, index(hour, "shift")] = 1
        equality[terminal_row, index(hour, "recovery")] = -1

    inequalities: list[tuple[dict[int, float], float]] = []
    shift_limits = [
        min(demand * (1 - policy.critical_load_fraction), demand * policy.interruptible_fraction)
        for demand in demand_mw
    ]
    for hour in range(hours):
        # Recovery cannot precede shifted work.
        coefficients: dict[int, float] = {}
        for prior in range(hour + 1):
            coefficients[index(prior, "recovery")] = 1
        for prior in range(hour):
            coefficients[index(prior, "shift")] = coefficients.get(index(prior, "shift"), 0) - 1
        inequalities.append((coefficients, 0.0))
        # Work older than the deadline must have been recovered.
        if hour >= policy.workload_deadline_hours:
            coefficients = {}
            for prior in range(hour + 1):
                coefficients[index(prior, "recovery")] = -1
            for prior in range(hour - policy.workload_deadline_hours + 1):
                coefficients[index(prior, "shift")] = coefficients.get(index(prior, "shift"), 0) + 1
            inequalities.append((coefficients, 0.0))
        if hour and policy.ramp_limit_mw_per_hour is not None:
            inequalities.append(
                (
                    {index(hour, "grid"): 1, index(hour - 1, "grid"): -1},
                    policy.ramp_limit_mw_per_hour,
                )
            )
        window = policy.maximum_interruption_hours + 1
        if hour + 1 >= window:
            start = hour + 1 - window
            # Continuous LP surrogate: a full interruption cannot occupy every hour in the window.
            inequalities.append(
                (
                    {index(item, "shift"): 1 for item in range(start, hour + 1)},
                    sum(
                        sorted(shift_limits[start : hour + 1])[: policy.maximum_interruption_hours]
                    ),
                )
            )
            if policy.ramp_limit_mw_per_hour is not None:
                inequalities.append(
                    (
                        {index(hour - 1, "grid"): 1, index(hour, "grid"): -1},
                        policy.ramp_limit_mw_per_hour,
                    )
                )
    # Conservative energy surrogate for the annual constrained-hour budget.
    shift_energy_limit = (
        max(demand_mw) * policy.interruptible_fraction * policy.annual_constrained_hour_budget
    )
    inequalities.append(({index(hour, "shift"): 1 for hour in range(hours)}, shift_energy_limit))
    inequalities.append(({index(hours - 1, "soc"): -1}, -initial_soc))
    inequality = lil_matrix((len(inequalities), hours * width))
    inequality_rhs = np.zeros(len(inequalities))
    for row_index, (coefficients, rhs) in enumerate(inequalities):
        for column, value in coefficients.items():
            inequality[row_index, column] = value
        inequality_rhs[row_index] = rhs
    solved = linprog(
        objective,
        A_ub=inequality.tocsr(),
        b_ub=inequality_rhs,
        A_eq=equality.tocsr(),
        b_eq=equality_rhs,
        bounds=bounds,
        method="highs",
        options={"presolve": True},
    )
    if not solved.success:
        raise RuntimeError(f"DeFlex optimization failed: {solved.message}")
    trace = []
    for hour in range(hours):
        trace.append({name: float(solved.x[index(hour, name)]) for name in VARIABLES})
    return {
        "classification": "synthetic_benchmark",
        "capacity_claim": False,
        "solver": "scipy-highs-linear-program",
        "objective": float(solved.fun),
        "critical_unserved_mwh": sum(row["critical_unserved"] for row in trace),
        "flexible_unserved_mwh": sum(row["flexible_unserved"] for row in trace),
        "shifted_mwh": sum(row["shift"] for row in trace),
        "recovered_mwh": sum(row["recovery"] for row in trace),
        "battery_discharge_mwh": sum(row["discharge"] for row in trace),
        "ending_soc_mwh": trace[-1]["soc"],
        "maximum_grid_import_mw": max(row["grid"] for row in trace),
        "unsafe_overstatement_hours": sum(
            row["grid"] > min(n0, n1) + 1e-7
            for row, n0, n1 in zip(trace, n0_envelope_mw, n1_envelope_mw)
        ),
        "trace": trace,
    }


def run_optimized_deflex_benchmark(
    records: list[BenchmarkRecord], hours: int = 168
) -> dict[str, Any]:
    # These are benchmark/demo dependencies, not dependencies of the reusable solver.
    from grid_data.deflex import dispatch_flexibility

    from .flex_study import SITE_SCENARIOS_MW, hourly_synthetic_profiles
    paired: dict[tuple[str, str], dict[str, BenchmarkRecord]] = {}
    for record in records:
        if record.scenario == "annual_median":
            paired.setdefault((record.network_id, record.node_id), {})[record.security_case] = (
                record
            )
    selected: dict[str, tuple[str, dict[str, BenchmarkRecord]]] = {}
    for (network, node), security in sorted(paired.items()):
        selected.setdefault(network, (node, security))
    results = []
    for network_id, (node_id, security) in selected.items():
        if set(security) != {"n_0", "n_1"}:
            raise ValueError("optimized DeFlex requires paired synthetic envelopes")
        for site_mw in SITE_SCENARIOS_MW:
            demand, n0, n1 = hourly_synthetic_profiles(
                site_mw,
                security["n_0"].truth_capacity_mw,
                security["n_1"].truth_capacity_mw,
                "annual_median",
            )
            demand, n0, n1 = demand[:hours], n0[:hours], n1[:hours]
            policy = FlexibilityPolicy(
                interruptible_fraction=0.10,
                maximum_interruption_hours=4,
                annual_constrained_hour_budget=120,
                recovery_hours=4,
                battery_power_mw=site_mw * 0.25,
                battery_energy_mwh=site_mw,
                charge_efficiency=0.92,
                discharge_efficiency=0.92,
                minimum_reserve_soc_fraction=0.10,
                ramp_limit_mw_per_hour=site_mw * 0.50,
                critical_load_fraction=0.80,
                workload_deadline_hours=24,
                battery_degradation_cost_per_mwh=1.0,
            )
            heuristic = dispatch_flexibility(demand, n0, n1, policy)
            optimized = optimize_flexibility(demand, n0, n1, policy)
            results.append(
                {
                    "network_id": network_id,
                    "node_id": node_id,
                    "site_load_mw": site_mw,
                    "hours": hours,
                    "policy": asdict(policy),
                    "heuristic_unserved_mwh": heuristic["unserved_mwh"],
                    "optimized_critical_unserved_mwh": optimized["critical_unserved_mwh"],
                    "optimized_flexible_unserved_mwh": optimized["flexible_unserved_mwh"],
                    "optimized_shifted_mwh": optimized["shifted_mwh"],
                    "unsafe_overstatement_hours": optimized["unsafe_overstatement_hours"],
                    "ending_soc_mwh": optimized["ending_soc_mwh"],
                    "truth_class": "synthetic_benchmark",
                    "capacity_claim": False,
                }
            )
    return {
        "schema_version": "optimized-deflex-benchmark-v1",
        "truth_class": "synthetic_benchmark",
        "capacity_claim": False,
        "cases": len(results),
        "hours_per_case": hours,
        "unsafe_overstatement_hours": sum(row["unsafe_overstatement_hours"] for row in results),
        "release_gate_passed": False,
        "release_gate_reason": "Synthetic optimization cannot establish operational capacity.",
        "results": results,
    }


def write_optimized_deflex(result: dict[str, Any], data_root: Path, run_id: str) -> dict[str, str]:
    root = data_root / "simulations" / "optimized-deflex-benchmark-v1" / run_id
    rows = result["results"]
    encoded = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    ).encode()
    rows_path = root / "results.jsonl.gz"
    atomic_write(rows_path, gzip.compress(encoded, mtime=0))
    metrics_path = root / "metrics.json"
    metrics = {key: value for key, value in result.items() if key != "results"}
    atomic_write(metrics_path, (json.dumps(metrics, indent=2, sort_keys=True) + "\n").encode())
    return {"results": str(rows_path), "metrics": str(metrics_path)}
