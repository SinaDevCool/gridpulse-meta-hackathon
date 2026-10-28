"""Electrical-sensitivity contingency selector and exhaustive fixed-injection audit."""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from grid_data.berlin_synthetic_capacity import BERLIN_NODES
from grid_data.network_study import NetworkModelInput, PandapowerProvider

from .backtest import (
    scaled_synthetic_model,
    synthetic_candidate_sample,
    synthetic_network_families,
)
from .graph import inspect_topology, select_contingencies
from .storage import atomic_write


def dc_injection_sensitivity(model: NetworkModelInput, candidate_bus: str) -> dict[str, float]:
    buses = [str(bus["id"]) for bus in model.buses]
    index = {bus: position for position, bus in enumerate(buses)}
    slack = str(model.generators[0]["bus"])
    matrix = np.zeros((len(buses), len(buses)))
    branch_data = []
    for branch in model.branches:
        start, end = str(branch["from_bus"]), str(branch["to_bus"])
        reactance = max(1e-6, float(branch["x_ohm_per_km"]) * float(branch["length_km"]))
        susceptance = 1.0 / reactance
        i, j = index[start], index[end]
        matrix[i, i] += susceptance
        matrix[j, j] += susceptance
        matrix[i, j] -= susceptance
        matrix[j, i] -= susceptance
        branch_data.append((str(branch["id"]), i, j, susceptance, float(branch["max_i_ka"])))
    keep = [position for position, bus in enumerate(buses) if bus != slack]
    injection = np.zeros(len(buses))
    injection[index[candidate_bus]] = 1.0
    injection[index[slack]] = -1.0
    try:
        reduced_angle = np.linalg.solve(matrix[np.ix_(keep, keep)], injection[keep])
    except np.linalg.LinAlgError as error:
        raise ValueError("synthetic topology is singular for DC sensitivity") from error
    angle = np.zeros(len(buses))
    angle[keep] = reduced_angle
    return {
        asset_id: abs(susceptance * (angle[i] - angle[j])) / max(rating, 1e-6)
        for asset_id, i, j, susceptance, rating in branch_data
    }


def select_contingencies_v4(model: NetworkModelInput, candidate_bus: str) -> dict[str, Any]:
    sensitivity = dc_injection_sensitivity(model, candidate_bus)
    inspection = inspect_topology(model)
    existing = select_contingencies(model, candidate_bus)["selected_asset_ids"]
    incident = {
        str(branch["id"])
        for branch in model.branches
        if candidate_bus in {str(branch["from_bus"]), str(branch["to_bus"])}
    }
    score = {}
    for branch in model.branches:
        asset = str(branch["id"])
        score[asset] = (
            100 * sensitivity.get(asset, 0.0)
            + 8 * int(asset in inspection.bridge_assets)
            + 4 * int(asset in incident)
            + 2 * int(asset in existing)
            + 1 / max(float(branch["max_i_ka"]), 1e-6)
        )
    declared = {str(item["element_id"]): item for item in model.contingencies}
    ranked = [
        asset
        for asset, _ in sorted(score.items(), key=lambda item: (-item[1], item[0]))
        if asset in declared
    ]
    # Retain at least half the reduction while maximizing safety recall.
    limit = max(1, len(declared) // 2)
    selected_assets = ranked[:limit]
    return {
        "selected": [declared[asset] for asset in selected_assets],
        "selected_asset_ids": selected_assets,
        "ranked_asset_ids": ranked,
        "selected_case_count": len(selected_assets),
        "full_case_count": len(declared),
        "reduction_ratio": 1 - len(selected_assets) / len(declared) if declared else 0.0,
        "sensitivity": sensitivity,
        "scores": score,
        "algorithm": "dc_injection_graph_safety_v4",
        "physics_verification_required": True,
        "capacity_claim": False,
    }


def _audit_family(
    model: NetworkModelInput, scenarios: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    names = {row[0]: row[1] for row in BERLIN_NODES}
    candidates = synthetic_candidate_sample(model, names, 10)[:2]
    provider = PandapowerProvider(maximum_capacity_mw=300, capacity_tolerance_mw=1.0)
    rows = []
    for scenario in scenarios:
        for node_id in candidates:
            scaled = scaled_synthetic_model(model, float(scenario["load_factor"]), node_id)
            incremental = {
                "id": "selector-audit-injection",
                "bus": node_id,
                "p_mw": 50.0,
                "q_mvar": 50.0 * math.tan(math.acos(0.96)),
            }
            audit_model = replace(scaled, loads=[*scaled.loads, incremental])
            exhaustive = provider.run_contingency_analysis(audit_model)
            cases = exhaustive.values["cases"]
            binding = max(
                cases,
                key=lambda item: (
                    len(item["violations"]),
                    float(item["maximum_line_loading_percent"]),
                    -float(item["minimum_voltage_pu"]),
                    str(item["id"]),
                ),
            )
            binding_asset = str(binding["id"]).removesuffix("-out")
            v3 = select_contingencies(model, node_id)
            v4 = select_contingencies_v4(model, node_id)
            rows.append(
                {
                    "network_id": model.model_id,
                    "scenario": scenario["id"],
                    "node_id": node_id,
                    "fixed_injection_mw": 50.0,
                    "binding_contingency": binding["id"],
                    "binding_asset": binding_asset,
                    "binding_max_loading_percent": binding["maximum_line_loading_percent"],
                    "binding_minimum_voltage_pu": binding["minimum_voltage_pu"],
                    "binding_violations": binding["violations"],
                    "v3_selected": binding_asset in v3["selected_asset_ids"],
                    "v4_selected": binding_asset in v4["selected_asset_ids"],
                    "v4_binding_rank": list(v4["ranked_asset_ids"]).index(binding_asset)
                    if binding_asset in v4["scores"]
                    else None,
                    "v4_selected_count": v4["selected_case_count"],
                    "full_case_count": v4["full_case_count"],
                    "v4_reduction_ratio": v4["reduction_ratio"],
                    "binding_dc_sensitivity": v4["sensitivity"].get(binding_asset),
                    "truth_class": "synthetic_benchmark",
                    "capacity_claim": False,
                }
            )
    return rows


def run_contingency_v4_audit(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    families = synthetic_network_families()
    with ThreadPoolExecutor(max_workers=4) as executor:
        grouped = list(executor.map(lambda model: _audit_family(model, scenarios), families))
    rows = [row for group in grouped for row in group]
    count = len(rows)
    v3_recall = sum(row["v3_selected"] for row in rows) / count
    v4_recall = sum(row["v4_selected"] for row in rows) / count
    minimum_family = min(
        sum(row["v4_selected"] for row in rows if row["network_id"] == family.model_id)
        / sum(row["network_id"] == family.model_id for row in rows)
        for family in families
    )
    reduction = sum(row["v4_reduction_ratio"] for row in rows) / count
    return {
        "schema_version": "contingency-selector-audit-v4",
        "truth_class": "synthetic_benchmark",
        "capacity_claim": False,
        "audit_cases": count,
        "v3_recall": v3_recall,
        "v4_recall": v4_recall,
        "minimum_family_recall": minimum_family,
        "mean_reduction_ratio": reduction,
        "release_gate_passed": v4_recall >= 0.95 and minimum_family >= 0.9 and reduction >= 0.5,
        "rows": rows,
    }


def write_contingency_audit(result: dict[str, Any], destination: Path) -> Path:
    atomic_write(destination, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    return destination
