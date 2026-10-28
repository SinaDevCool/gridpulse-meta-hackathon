"""Representative solved hourly AC and publication-aware mock outage study."""

from __future__ import annotations

import gzip
import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from grid_data.network_study import PandapowerProvider

from .backtest import synthetic_network_families
from .contingency_v4 import select_contingencies_v4
from .storage import atomic_write
from .synthetic_operator import iter_synthetic_table, read_synthetic_table


def select_representative_states(
    manifest_path: Path, data_root: Path
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    requests = read_synthetic_table(data_root, manifest, "queue_requests")
    outages = read_synthetic_table(data_root, manifest, "outages")
    candidates: dict[str, str] = {}
    for request in requests:
        candidates.setdefault(request["network_id"], request["requested_bus"])
    start = datetime.fromisoformat(manifest["start_at"])
    selected: dict[str, set[str]] = {}
    for network_id in candidates:
        stamps = {
            (start + timedelta(hours=offset)).isoformat()
            for offset in (
                0,
                manifest["hours"] // 4,
                manifest["hours"] // 2,
                3 * manifest["hours"] // 4,
            )
        }
        revised = sorted(
            {
                row["starts_at"]
                for row in outages
                if row["network_id"] == network_id and row["revision"] == 2
            }
        )[:2]
        stamps.update(revised)
        selected[network_id] = stamps
    states = {network_id: [] for network_id in candidates}
    for row in iter_synthetic_table(data_root, manifest, "hourly_operating_states"):
        if (
            row["network_id"] in candidates
            and row["bus_id"] == candidates[row["network_id"]]
            and row["timestamp"] in selected[row["network_id"]]
        ):
            states[row["network_id"]].append(row)
    if any(len(rows) < 4 for rows in states.values()):
        raise ValueError("representative hourly state selection is incomplete")
    context = {"manifest": manifest, "outages": outages, "requests": requests}
    return states, context


def _active_outage_assets(
    outages: list[dict[str, Any]], network_id: str, timestamp: datetime
) -> list[str]:
    latest: dict[str, dict[str, Any]] = {}
    for row in outages:
        if (
            row["network_id"] != network_id
            or datetime.fromisoformat(row["published_at"]) > timestamp
        ):
            continue
        current = latest.get(row["event_id"])
        if current is None or row["revision"] > current["revision"]:
            latest[row["event_id"]] = row
    return sorted(
        row["asset_id"]
        for row in latest.values()
        if datetime.fromisoformat(row["starts_at"])
        <= timestamp
        < datetime.fromisoformat(row["ends_at"])
    )


def _reserved_at(
    requests: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    network_id: str,
    node: str,
    timestamp: datetime,
) -> float:
    request_ids = {
        row["request_id"]
        for row in requests
        if row["network_id"] == network_id and row["requested_bus"] == node
    }
    return sum(
        float(row["firm_mw_offered"]) + float(row["conditional_mw_offered"])
        for row in outcomes
        if row["request_id"] in request_ids
        and datetime.fromisoformat(row["decision_at"]) <= timestamp
    )


def _solve_family(
    model,
    states: list[dict[str, Any]],
    outages: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    provider = PandapowerProvider(
        maximum_capacity_mw=300, capacity_tolerance_mw=2.0, incremental_load_power_factor=0.96
    )
    rows = []
    for state in sorted(states, key=lambda item: item["timestamp"]):
        timestamp = datetime.fromisoformat(state["timestamp"])
        node = state["bus_id"]
        active = _active_outage_assets(outages, model.model_id, timestamp)
        branches = [branch for branch in model.branches if str(branch["id"]) not in active]
        remaining = {str(branch["id"]) for branch in branches}
        contingencies = [
            contingency
            for contingency in model.contingencies
            if str(contingency["element_id"]) in remaining
        ]
        reserved = _reserved_at(requests, outcomes, model.model_id, node, timestamp)
        committed = float(state["synthetic_demand_mw"]) + reserved
        load = {
            "id": "representative-hour-committed-load",
            "bus": node,
            "p_mw": committed,
            "q_mvar": committed * math.tan(math.acos(0.96)),
        }
        operating_model = replace(
            model,
            branches=branches,
            contingencies=contingencies,
            loads=[*model.loads, load],
            connection_bus=node,
        )
        selection = select_contingencies_v4(operating_model, node)
        selected_model = replace(operating_model, contingencies=selection["selected"])
        base = provider.run_detailed_base_case(operating_model)
        capacity = provider.calculate_import_capacity(selected_model)
        approximate = float(state["synthetic_n1_envelope_mw"])
        solved = float(capacity.values["firm_import_capacity_mw"])
        rows.append(
            {
                "network_id": model.model_id,
                "node_id": node,
                "timestamp": state["timestamp"],
                "active_outage_assets": active,
                "reserved_commitments_mw": reserved,
                "committed_load_mw": committed,
                "converged": base.converged,
                "passes": base.values.get("passes"),
                "violations": base.values.get("violations", []),
                "bus_voltage_pu": base.values.get("bus_voltage_pu", {}),
                "line_loading_percent": base.values.get("line_loading_percent", {}),
                "solved_selected_n1_envelope_mw": solved,
                "approximate_n1_envelope_mw": approximate,
                "approximation_error_mw": approximate - solved,
                "unsafe_overstatement": approximate > solved + 1.0,
                "binding_constraint": capacity.values["binding_constraint"],
                "binding_case": capacity.values["binding_case"],
                "selected_contingencies": selection["selected_asset_ids"],
                "truth_class": "synthetic_benchmark",
                "capacity_claim": False,
            }
        )
    return rows


def run_representative_hourly_ac(manifest_path: Path, data_root: Path) -> dict[str, Any]:
    states, context = select_representative_states(manifest_path, data_root)
    manifest = context["manifest"]
    outcomes = read_synthetic_table(data_root, manifest, "connection_study_outcomes")
    models = {model.model_id: model for model in synthetic_network_families()}
    with ThreadPoolExecutor(max_workers=4) as executor:
        grouped = list(
            executor.map(
                lambda network_id: _solve_family(
                    models[network_id],
                    states[network_id],
                    context["outages"],
                    context["requests"],
                    outcomes,
                ),
                sorted(states),
            )
        )
    rows = [row for group in grouped for row in group]
    errors = [row["approximation_error_mw"] for row in rows]
    return {
        "schema_version": "representative-hourly-ac-v1",
        "truth_class": "synthetic_benchmark",
        "capacity_claim": False,
        "cases": len(rows),
        "convergence_rate": sum(row["converged"] is True for row in rows) / len(rows),
        "unsafe_overstatement_rate": sum(row["unsafe_overstatement"] for row in rows) / len(rows),
        "mean_absolute_approximation_error_mw": sum(abs(value) for value in errors) / len(errors),
        "maximum_overstatement_mw": max(errors),
        "release_gate_passed": False,
        "release_gate_reason": "Representative synthetic hours do not validate a real network.",
        "rows": rows,
    }


def write_hourly_ac(result: dict[str, Any], data_root: Path, run_id: str) -> dict[str, str]:
    root = data_root / "simulations" / "representative-hourly-ac-v1" / run_id
    rows = result["rows"]
    encoded = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    ).encode()
    row_path = root / "rows.jsonl.gz"
    atomic_write(row_path, gzip.compress(encoded, mtime=0))
    metrics = {key: value for key, value in result.items() if key != "rows"}
    metrics_path = root / "metrics.json"
    atomic_write(metrics_path, (json.dumps(metrics, indent=2, sort_keys=True) + "\n").encode())
    return {"rows": str(row_path), "metrics": str(metrics_path)}
