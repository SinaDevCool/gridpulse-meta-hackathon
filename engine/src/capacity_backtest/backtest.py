"""Reproducible synthetic benchmark and conservative reduced-information evaluation."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import yaml

from grid_data.berlin_synthetic_capacity import (
    BERLIN_NODES,
    SLACK_NODE_ID,
    build_berlin_synthetic_model,
)
from grid_data.network_study import NetworkModelInput, PandapowerProvider

from .contracts import TruthClass, coerce_truth_class
from .graph import inspect_topology, node_features, select_contingencies


@dataclass(frozen=True)
class BenchmarkRecord:
    network_id: str
    node_id: str
    node_name: str
    scenario: str
    security_case: str
    truth_capacity_mw: float
    binding_constraint: str
    public_voltage_kv: float
    public_degree: int
    public_distance_to_slack_km: float
    edge_disjoint_paths: int
    incident_bridge_count: int
    articulation: bool
    graph_provider: str
    graph_selected_case_count: int
    full_contingency_case_count: int
    contingency_reduction_ratio: float
    selector_captured_binding_case: bool | None
    validation_class: TruthClass = TruthClass.SYNTHETIC_BENCHMARK

    def __post_init__(self) -> None:
        object.__setattr__(self, "validation_class", coerce_truth_class(self.validation_class))


@dataclass(frozen=True)
class EstimateRecord:
    network_id: str
    node_id: str
    scenario: str
    security_case: str
    estimated_capacity_mw: float | None
    lower_mw: float | None
    upper_mw: float | None
    band: str
    abstained: bool
    abstention_reasons: list[str]
    truth_class: TruthClass = TruthClass.EXPERIMENTAL_ESTIMATE

    def __post_init__(self) -> None:
        object.__setattr__(self, "truth_class", coerce_truth_class(self.truth_class))


def load_study(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def scaled_synthetic_model(
    model: NetworkModelInput, factor: float, connection_bus: str
) -> NetworkModelInput:
    loads = [
        {**item, "p_mw": item["p_mw"] * factor, "q_mvar": item["q_mvar"] * factor}
        for item in model.loads
    ]
    return replace(model, loads=loads, connection_bus=connection_bus)


def synthetic_network_families() -> list[NetworkModelInput]:
    """Structurally distinct synthetic twins for network-family validation."""
    base = build_berlin_synthetic_model()
    families = []
    specifications = (
        ((), 1.00),
        ((1,), 0.82),
        ((4,), 1.18),
        ((7,), 0.94),
        ((2,), 0.76),
        ((10,), 1.08),
        ((3, 8), 1.25),
        ((5,), 0.88),
    )
    for index, (drops, rating) in enumerate(specifications, start=1):
        branches = [dict(item) for item in base.branches]
        branches = [item for position, item in enumerate(branches) if position not in drops]
        for branch in branches:
            branch["max_i_ka"] = round(float(branch["max_i_ka"]) * rating, 4)
        active = {str(item["id"]) for item in branches}
        contingencies = [item for item in base.contingencies if str(item["element_id"]) in active]
        families.append(
            replace(
                base,
                branches=branches,
                contingencies=contingencies,
                model_id=f"{base.model_id}-family-{index}",
            )
        )
    return families


def synthetic_candidate_sample(
    model: NetworkModelInput, names: dict[str, str], count: int
) -> list[str]:
    """Deterministic structurally stratified sample of eligible non-slack buses."""
    eligible = [node_id for node_id in names if node_id != SLACK_NODE_ID]
    if count >= len(eligible):
        return eligible
    features = {node_id: node_features(model, node_id) for node_id in eligible}
    # Prefer rare structural classes, then spread deterministically across the public list.
    ordered = sorted(
        eligible,
        key=lambda node_id: (
            features[node_id].articulation,
            features[node_id].incident_bridge_count,
            features[node_id].edge_disjoint_paths,
            node_id,
        ),
        reverse=True,
    )
    stride_order = ordered[::2] + ordered[1::2]
    return stride_order[:count]


def _degrees(model: NetworkModelInput) -> dict[str, int]:
    result = {str(bus["id"]): 0 for bus in model.buses}
    for branch in model.branches:
        result[str(branch["from_bus"])] += 1
        result[str(branch["to_bus"])] += 1
    return result


def _shortest_distance(model: NetworkModelInput, target: str) -> float:
    adjacency: dict[str, list[tuple[str, float]]] = {str(bus["id"]): [] for bus in model.buses}
    for branch in model.branches:
        start, end = str(branch["from_bus"]), str(branch["to_bus"])
        distance = float(branch["length_km"])
        adjacency[start].append((end, distance))
        adjacency[end].append((start, distance))
    distances = {SLACK_NODE_ID: 0.0}
    pending = {SLACK_NODE_ID}
    while pending:
        current = min(pending, key=distances.get)
        pending.remove(current)
        for neighbor, distance in adjacency[current]:
            candidate = distances[current] + distance
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                pending.add(neighbor)
    return round(distances[target], 3)


def _run_family(
    base: NetworkModelInput,
    study: dict[str, object],
    names: dict[str, str],
    minimum_candidates: int,
) -> list[BenchmarkRecord]:
    provider = PandapowerProvider(
        maximum_capacity_mw=300,
        capacity_tolerance_mw=1.0,
        incremental_load_power_factor=0.96,
    )
    records = []
    degrees = _degrees(base)
    topology = inspect_topology(base)
    candidate_nodes = synthetic_candidate_sample(base, names, minimum_candidates)
    for scenario in study["scenarios"]:
        for node_id in candidate_nodes:
            if node_id == SLACK_NODE_ID:
                continue
            model = scaled_synthetic_model(base, float(scenario["load_factor"]), node_id)
            features = node_features(base, node_id)
            selection = select_contingencies(base, node_id)
            for security in study["security_cases"]:
                # Exhaustive N-1 is retained on a stratified audit node in every network family;
                # remaining cases use the selector so routine CI remains bounded.
                exhaustive_audit = security == "n_1" and node_id in candidate_nodes[:2]
                contingencies = (
                    []
                    if security == "n_0"
                    else base.contingencies
                    if exhaustive_audit
                    else selection["selected"]
                )
                evaluated = replace(model, contingencies=contingencies)
                result = provider.calculate_import_capacity(evaluated)
                binding = str(result.values.get("binding_case") or "")
                captured = (
                    None
                    if not exhaustive_audit
                    else binding.removesuffix("-out") in selection["selected_asset_ids"]
                )
                records.append(
                    BenchmarkRecord(
                        base.model_id,
                        node_id,
                        names[node_id],
                        str(scenario["id"]),
                        str(security),
                        float(result.values["firm_import_capacity_mw"]),
                        str(result.values["binding_constraint"]),
                        110.0,
                        degrees[node_id],
                        _shortest_distance(base, node_id),
                        features.edge_disjoint_paths,
                        features.incident_bridge_count,
                        features.articulation,
                        topology.provider,
                        len(selection["selected"]),
                        int(selection["full_case_count"]),
                        float(selection["reduction_ratio"]),
                        captured,
                    )
                )
    return records


def run_benchmark(study: dict[str, object]) -> list[BenchmarkRecord]:
    names = {row[0]: row[1] for row in BERLIN_NODES}
    minimum_candidates = int(study.get("routine_candidate_count", 10))
    if minimum_candidates < 10:
        raise ValueError("routine benchmark requires at least ten unique candidates")
    families = synthetic_network_families()
    with ThreadPoolExecutor(max_workers=min(4, len(families))) as executor:
        family_records = list(
            executor.map(lambda base: _run_family(base, study, names, minimum_candidates), families)
        )
    return [record for records in family_records for record in records]


def _band(value: float | None, thresholds: list[float]) -> str:
    if value is None:
        return "unknown"
    lower = 0.0
    for threshold in thresholds:
        if value < threshold:
            return f"{lower:g}-{threshold:g} MW"
        lower = threshold
    return f">={thresholds[-1]:g} MW"


def estimate(records: list[BenchmarkRecord], thresholds: list[float]) -> list[EstimateRecord]:
    # Leave-one-network-out: no truth from the target topology may enter its estimate.
    estimates = []
    for record in records:
        peers = [
            item.truth_capacity_mw
            for item in records
            if item.network_id != record.network_id
            and item.scenario == record.scenario
            and item.security_case == record.security_case
            and abs(item.public_degree - record.public_degree) <= 1
            and abs(item.edge_disjoint_paths - record.edge_disjoint_paths) <= 1
        ]
        if len(peers) < 2:
            estimates.append(
                EstimateRecord(
                    record.network_id,
                    record.node_id,
                    record.scenario,
                    record.security_case,
                    None,
                    None,
                    None,
                    "unknown",
                    True,
                    ["insufficient structurally comparable held-out peers"],
                )
            )
            continue
        ordered = sorted(peers)
        conservative = ordered[max(0, int(len(ordered) * 0.20) - 1)]
        lower = ordered[max(0, int(len(ordered) * 0.05) - 1)]
        upper = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        estimates.append(
            EstimateRecord(
                record.network_id,
                record.node_id,
                record.scenario,
                record.security_case,
                round(conservative, 3),
                round(lower, 3),
                round(upper, 3),
                _band(conservative, thresholds),
                False,
                [],
            )
        )
    return estimates


def evaluate(
    truth: list[BenchmarkRecord], estimates: list[EstimateRecord], study: dict[str, object]
) -> dict[str, object]:
    joined = [
        (actual, predicted)
        for actual, predicted in zip(truth, estimates)
        if predicted.estimated_capacity_mw is not None
    ]
    errors = [
        predicted.estimated_capacity_mw - actual.truth_capacity_mw for actual, predicted in joined
    ]
    absolute = [abs(error) for error in errors]
    overstatements = [error for error in errors if error > 0]
    severe_limit = float(study["evaluation"]["severe_overstatement_mw"])
    coverage = [
        predicted.lower_mw <= actual.truth_capacity_mw <= predicted.upper_mw
        for actual, predicted in joined
    ]
    by_group: dict[tuple[str, str], list[tuple[BenchmarkRecord, EstimateRecord]]] = {}
    for actual, predicted in joined:
        by_group.setdefault((actual.scenario, actual.security_case), []).append((actual, predicted))
    recalls = []
    for group in by_group.values():
        limit = min(10, len(group))
        true_top = {
            item[0].node_id
            for item in sorted(group, key=lambda pair: pair[0].truth_capacity_mw, reverse=True)[
                :limit
            ]
        }
        estimated_top = {
            item[0].node_id
            for item in sorted(group, key=lambda pair: pair[1].estimated_capacity_mw, reverse=True)[
                :limit
            ]
        }
        recalls.append(len(true_top & estimated_top) / limit)
    count = len(joined)
    metrics = {
        "evaluated_count": count,
        "abstention_count": len(estimates) - count,
        "mean_absolute_error_mw": round(sum(absolute) / count, 3) if count else None,
        "median_absolute_error_mw": round(median(absolute), 3) if absolute else None,
        "overstatement_rate": round(len(overstatements) / count, 4) if count else None,
        "severe_overstatement_rate": round(sum(error > severe_limit for error in errors) / count, 4)
        if count
        else None,
        "interval_coverage": round(sum(coverage) / count, 4) if count else None,
        "top_10_recall": round(sum(recalls) / len(recalls), 4) if recalls else None,
        "mean_contingency_reduction_ratio": round(
            sum(item.contingency_reduction_ratio for item in truth) / len(truth), 4
        ),
        "topology_provider": truth[0].graph_provider if truth else "unavailable",
        "network_family_count": len({item.network_id for item in truth}),
        "contingency_selector_audit_count": sum(
            item.selector_captured_binding_case is not None for item in truth
        ),
        "contingency_selector_recall": round(
            sum(item.selector_captured_binding_case is True for item in truth)
            / max(1, sum(item.selector_captured_binding_case is not None for item in truth)),
            4,
        ),
    }
    gates = study["evaluation"]
    unique_candidates = len({item.node_id for item in truth})
    metrics["unique_candidate_count"] = unique_candidates
    metrics["ranking_gate_passed"] = bool(
        metrics["top_10_recall"] is not None
        and metrics["top_10_recall"] >= gates["top_10_recall_minimum"]
        and unique_candidates >= 10
        and metrics["network_family_count"] >= 3
    )
    metrics["capacity_gate_passed"] = bool(
        metrics["overstatement_rate"] is not None
        and metrics["interval_coverage"] is not None
        and metrics["overstatement_rate"] <= gates["overstatement_rate_maximum"]
        and metrics["severe_overstatement_rate"] <= gates["severe_overstatement_rate_maximum"]
        and metrics["interval_coverage"] >= gates["interval_coverage_minimum"]
        and metrics["mean_absolute_error_mw"] <= gates["mean_absolute_error_mw_maximum"]
        and metrics["median_absolute_error_mw"] <= gates["median_absolute_error_mw_maximum"]
        and metrics["network_family_count"] >= 3
        and metrics["contingency_selector_recall"] >= gates["contingency_selector_recall_minimum"]
    )
    return metrics


def run_and_write(study_path: Path, output_dir: Path) -> dict[str, object]:
    study = load_study(study_path)
    truth = run_benchmark(study)
    estimates = estimate(truth, [float(value) for value in study["capacity_bands_mw"]])
    metrics = evaluate(truth, estimates, study)
    from .flex_study import run_synthetic_flexibility_study

    flexibility = run_synthetic_flexibility_study(truth)
    berlin = {
        "classification": "public_evidence_applicability",
        "capacity_mw": None,
        "capacity_band": "unknown",
        "relative_ranking_released": False,
        "reason": "Synthetic cross-network validation cannot establish live Berlin capacity; operator-grade electrical inputs remain unavailable.",
        "required_operator_inputs": [
            "equipment ratings",
            "switching state",
            "existing nodal demand",
            "contracted and queued demand",
            "N-1 policy",
            "validated outcomes",
        ],
    }
    payload = {
        "study": study,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_classification": "synthetic_demonstration",
        "records": [asdict(item) for item in truth],
        "estimates": [asdict(item) for item in estimates],
        "metrics": metrics,
        "synthetic_flexibility": flexibility,
        "berlin_release": berlin,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "backtest-results.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload
