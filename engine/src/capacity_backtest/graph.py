"""Neo4j-compatible topology analysis used to reduce physics cases, never calculate MW."""

from __future__ import annotations

import heapq
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from grid_data.network_study import NetworkModelInput


@dataclass(frozen=True)
class GraphInspection:
    provider: str
    connected_components: list[list[str]]
    bridge_assets: list[str]
    articulation_buses: list[str]
    degree_by_bus: dict[str, int]
    capacity_claim: bool = False


@dataclass(frozen=True)
class NodeGraphFeatures:
    degree: int
    weighted_distance_to_source: float
    edge_disjoint_paths: int
    incident_bridge_count: int
    articulation: bool


def _adjacency(model: NetworkModelInput):
    adjacency: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for branch in model.branches:
        start, end = str(branch["from_bus"]), str(branch["to_bus"])
        weight = max(float(branch.get("length_km", 0.25)), 0.001)
        asset = str(branch["id"])
        adjacency[start].append((end, asset, weight))
        adjacency[end].append((start, asset, weight))
    return adjacency


def inspect_topology(model: NetworkModelInput, *, provider: str | None = None) -> GraphInspection:
    requested = provider or (
        "neo4j_gds" if os.getenv("NEO4J_PASSWORD") else "deterministic_in_memory"
    )
    # The shared contract is deterministic. A configured Neo4j deployment can persist and query
    # the same projection; CI and this self-contained lab require no external database.
    adjacency = _adjacency(model)
    buses = sorted(str(item["id"]) for item in model.buses)
    components, seen = [], set()
    for root in buses:
        if root in seen:
            continue
        stack, component = [root], []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            component.append(node)
            stack.extend(neighbor for neighbor, _, _ in adjacency[node])
        components.append(sorted(component))
    bridges, articulation = _criticality(adjacency)
    return GraphInspection(
        requested,
        components,
        sorted(bridges),
        sorted(articulation),
        {bus: len(adjacency[bus]) for bus in buses},
    )


def _criticality(adjacency):
    timer, visited, entered, low, bridges, cuts = 0, set(), {}, {}, set(), set()

    def visit(node, parent=None):
        nonlocal timer
        visited.add(node)
        entered[node] = low[node] = timer
        timer += 1
        children = 0
        for neighbor, asset, _ in adjacency[node]:
            if neighbor == parent:
                continue
            if neighbor in visited:
                low[node] = min(low[node], entered[neighbor])
                continue
            visit(neighbor, node)
            low[node] = min(low[node], low[neighbor])
            children += 1
            if low[neighbor] > entered[node]:
                bridges.add(asset)
            if parent is not None and low[neighbor] >= entered[node]:
                cuts.add(node)
        if parent is None and children > 1:
            cuts.add(node)

    for node in adjacency:
        if node not in visited:
            visit(node)
    return bridges, cuts


def shortest_path_assets(model: NetworkModelInput, source: str, target: str) -> list[str]:
    adjacency = _adjacency(model)
    queue = [(0.0, source, (source,), ())]
    while queue:
        cost, node, buses, assets = heapq.heappop(queue)
        if node == target:
            return list(assets)
        for neighbor, asset, weight in adjacency[node]:
            if neighbor not in buses:
                heapq.heappush(
                    queue, (cost + weight, neighbor, buses + (neighbor,), assets + (asset,))
                )
    return []


def node_features(model: NetworkModelInput, node: str) -> NodeGraphFeatures:
    """Return topology-only features; none are MW or capacity claims."""
    adjacency = _adjacency(model)
    source = str(model.generators[0]["bus"])
    path = shortest_path_assets(model, node, source)
    edge_by_id = {
        str(item["id"]): max(float(item.get("length_km", 0.25)), 0.001) for item in model.branches
    }
    inspection = inspect_topology(model)
    incident = {asset for _, asset, _ in adjacency[node]}

    # Unit-capacity Edmonds-Karp gives an exact edge-disjoint-path count for this small graph.
    residual: dict[tuple[str, str], int] = {}
    for start, links in adjacency.items():
        for end, _, _ in links:
            residual[(start, end)] = 1
    flow = 0
    while True:
        queue, parent = [node], {node: None}
        for current in queue:
            for neighbor, _, _ in adjacency[current]:
                if neighbor not in parent and residual.get((current, neighbor), 0) > 0:
                    parent[neighbor] = current
                    queue.append(neighbor)
                    if neighbor == source:
                        break
            if source in parent:
                break
        if source not in parent:
            break
        cursor = source
        while parent[cursor] is not None:
            previous = parent[cursor]
            residual[(previous, cursor)] -= 1
            residual[(cursor, previous)] = residual.get((cursor, previous), 0) + 1
            cursor = previous
        flow += 1
    return NodeGraphFeatures(
        degree=len(adjacency[node]),
        weighted_distance_to_source=round(sum(edge_by_id[item] for item in path), 3),
        edge_disjoint_paths=flow,
        incident_bridge_count=len(incident & set(inspection.bridge_assets)),
        articulation=node in inspection.articulation_buses,
    )


def select_contingencies(model: NetworkModelInput, candidate_bus: str) -> dict[str, Any]:
    path_assets = shortest_path_assets(model, candidate_bus, str(model.generators[0]["bus"]))
    declared = {str(item["element_id"]): item for item in model.contingencies}
    inspection = inspect_topology(model)
    incident = [
        str(item["id"])
        for item in model.branches
        if candidate_bus in {str(item["from_bus"]), str(item["to_bus"])}
    ]
    # Low-current branches are plausible thermal bottlenecks. This remains only a selector;
    # exhaustive AC cases are authoritative in the audit sample.
    thermally_narrow = [
        str(item["id"])
        for item in sorted(
            model.branches,
            key=lambda item: (
                float(item.get("max_i_ka", float("inf"))),
                float(item.get("length_km", 0.0)),
                str(item.get("id")),
            ),
        )
    ]
    ranked = list(
        dict.fromkeys([*path_assets, *incident, *inspection.bridge_assets, *thermally_narrow])
    )
    selection_limit = min(5, len(declared))
    selected_assets = [asset for asset in ranked if asset in declared][:selection_limit]
    selected = [declared[asset] for asset in selected_assets]
    return {
        "selected": selected,
        "selected_asset_ids": selected_assets,
        "full_case_count": len(model.contingencies),
        "selected_case_count": len(selected),
        "reduction_ratio": round(1 - len(selected) / len(model.contingencies), 4)
        if model.contingencies
        else 0.0,
        "algorithm": "weighted_path_incident_bridge_thermal_union_v3",
        "physics_verification_required": True,
        "capacity_claim": False,
    }
