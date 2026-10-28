from capacity_backtest.graph import (
    inspect_topology,
    node_features,
    select_contingencies,
    shortest_path_assets,
)
from grid_data.berlin_synthetic_capacity import BERLIN_NODES, build_berlin_synthetic_model


def test_graph_inspection_covers_all_berlin_synthetic_nodes_without_capacity_claim():
    model = build_berlin_synthetic_model()
    inspection = inspect_topology(model)
    assert len(inspection.connected_components) == 1
    assert len(inspection.connected_components[0]) == len(BERLIN_NODES)
    assert inspection.capacity_claim is False


def test_graph_selector_reduces_cases_but_requires_physics():
    model = build_berlin_synthetic_model()
    candidate = BERLIN_NODES[0][0]
    selection = select_contingencies(model, candidate)
    assert shortest_path_assets(model, candidate, model.generators[0]["bus"])
    assert 1 <= selection["selected_case_count"] <= 5
    assert selection["selected_case_count"] < selection["full_case_count"]
    assert selection["full_case_count"] == len(model.contingencies)
    assert selection["reduction_ratio"] > 0.5
    assert selection["physics_verification_required"] is True
    assert selection["capacity_claim"] is False


def test_node_features_are_topological_not_capacity_claims():
    model = build_berlin_synthetic_model()
    features = node_features(model, BERLIN_NODES[0][0])
    assert features.degree >= 2
    assert features.weighted_distance_to_source > 0
    assert features.edge_disjoint_paths >= 1
