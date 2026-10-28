from __future__ import annotations

import pytest

from capacity_backtest.capacity_study.aggregation import RealizationEnvelope, aggregate_capacity
from capacity_backtest.capacity_study.blockers import capacity_blockers
from capacity_backtest.capacity_study.contingencies import exhaustive_n_minus_one
from capacity_backtest.capacity_study.ensemble import build_network_ensemble
from capacity_backtest.capacity_study.operating_states import (
    assemble_operating_states,
    mock_operator_series,
)
from capacity_backtest.capacity_study.pcc import generate_pcc_hypotheses
from capacity_backtest.contracts import TruthClass
from grid_data.network_study import NetworkModelInput


def network() -> NetworkModelInput:
    return NetworkModelInput(
        buses=[
            {"id": "slack", "vn_kv": 110, "latitude": 52.5, "longitude": 13.3},
            {"id": "pcc-a", "vn_kv": 110, "latitude": 52.51, "longitude": 13.4},
            {"id": "pcc-b", "vn_kv": 110, "latitude": 52.6, "longitude": 13.5},
        ],
        branches=[
            {
                "id": "line-a",
                "from_bus": "slack",
                "to_bus": "pcc-a",
                "length_km": 10,
                "r_ohm_per_km": 0.1,
                "x_ohm_per_km": 0.2,
                "c_nf_per_km": 10,
                "max_i_ka": 1,
            }
        ],
        transformers=[],
        loads=[{"id": "load-a", "bus": "pcc-a", "p_mw": 10, "q_mvar": 2}],
        generators=[{"id": "grid", "bus": "slack", "kind": "external_grid"}],
        switches=[],
        contingencies=[],
        connection_bus="pcc-a",
        study_year=2026,
        provenance={"source_url": "fixture://network", "license": "test"},
        model_id="test-network",
        model_version="v1",
        validation_class="synthetic_demonstration",
    )


def pccs():
    return generate_pcc_hypotheses(
        site_latitude=52.5,
        site_longitude=13.4,
        requested_capacity_mw=30,
        operator_id="operator",
        buses=network().buses,
        maximum_candidates=2,
    )


def test_pcc_hypotheses_are_unconfirmed_and_ranked() -> None:
    values = pccs()
    assert len(values) == 2
    assert values[0].status.value == "geographic_hypothesis"
    assert values[0].truth_class == TruthClass.EXPERIMENTAL_ESTIMATE
    assert values[0].confidence >= values[1].confidence


def test_operating_state_assembly_keeps_reservations_explicit() -> None:
    result = assemble_operating_states(
        series_id="states",
        timestamps=["2026-01-01T00:00:00+00:00"],
        regional_load_mw=[100],
        regional_generation_mw=[20],
        nodal_load_fraction=0.1,
        nodal_generation_fraction=0.1,
        committed_connections_mw=[3],
        reservations_mw=[4],
        evidence_cutoff="2025-12-31T00:00:00+00:00",
        active_outage_ids=[["line-a"]],
    )
    assert result.points[0].net_committed_load_mw == 15
    assert result.points[0].reservations_mw == 4
    assert result.points[0].active_outage_ids == ("line-a",)


def test_mock_operator_series_is_seeded_and_explicitly_synthetic() -> None:
    kwargs = {
        "timestamps": ["2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00"],
        "evidence_cutoff": "2025-12-31T00:00:00+00:00",
        "seed": 7,
        "peak_load_mw": 100,
        "generation_capacity_mw": 20,
    }
    assert mock_operator_series(**kwargs) == mock_operator_series(**kwargs)
    assert mock_operator_series(**kwargs).truth_class == TruthClass.SYNTHETIC_DEMONSTRATION


def test_exhaustive_n_minus_one_and_seeded_ensemble() -> None:
    model = exhaustive_n_minus_one(network())
    assert [item["element_id"] for item in model.contingencies] == ["line-a"]
    first = build_network_ensemble(model, pccs(), samples_per_pcc=2, seed=11)
    second = build_network_ensemble(model, pccs(), samples_per_pcc=2, seed=11)
    assert [item.parameter_set_id for item in first] == [item.parameter_set_id for item in second]
    assert sum(item.probability_weight for item in first) == 1


def test_capacity_aggregation_reports_duration_uncertainty_and_events() -> None:
    values = aggregate_capacity(
        [
            RealizationEnvelope(
                "a", 0.5, (10, 20, 30, 40), ("line",) * 4, capacity_is_lower_bound=True
            ),
            RealizationEnvelope("b", 0.4, (20, 30, 40, 50), ("transformer",) * 4),
            RealizationEnvelope("failed", 0.1, (), ("non_convergence",), False),
        ],
        requested_capacity_mw=35,
        interval_hours=1,
    )
    assert values.minimum_mw == 10
    assert values.maximum_mw == 50
    assert values.p10_mw <= values.p50_mw <= values.p90_mw
    assert values.failed_realization_fraction == pytest.approx(0.1)
    assert values.lower_bound_realization_fraction == pytest.approx(5 / 9)
    assert values.curtailment_event_count == 1
    assert values.availability_capacities[0].availability == 1


def test_missing_operator_data_produces_structured_blockers() -> None:
    blockers = capacity_blockers(
        pccs()[0],
        operator_topology=False,
        operator_ratings=False,
        operator_loading=False,
        operator_queue=False,
        operator_contingencies=False,
    )
    codes = {item.code for item in blockers}
    assert {"pcc_unconfirmed", "topology_reconstructed", "short_circuit_study_missing"} <= codes
