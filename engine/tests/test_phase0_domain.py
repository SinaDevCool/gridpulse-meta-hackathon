from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain import (
    CapacityEnvelopeResult,
    DispatchPoint,
    DispatchTrajectory,
    EvidenceReference,
    FlexibilityPortfolio,
    FlexibilityResource,
    ForecastDistribution,
    ForecastPoint,
    NetworkEnvelope,
    ResourceKind,
    RunProvenance,
    StudyHorizon,
    StudyScenario,
)

SHA = "a" * 64


def evidence(retrieved_at: str = "2026-01-01T00:00:00+00:00") -> EvidenceReference:
    return EvidenceReference(
        evidence_id="e-1",
        source_id="synthetic-fixture",
        snapshot_hash=SHA,
        retrieved_at=retrieved_at,
        truth_class=TruthClass.SYNTHETIC_BENCHMARK,
        source_locator="fixture://phase0",
    )


def portfolio() -> FlexibilityPortfolio:
    return FlexibilityPortfolio(
        portfolio_id="p-1",
        resources=(
            FlexibilityResource("battery-1", ResourceKind.BATTERY, 10, 20),
            FlexibilityResource("workload-1", ResourceKind.FLEXIBLE_WORKLOAD, 5),
        ),
    )


def scenario(*, item: EvidenceReference | None = None) -> StudyScenario:
    return StudyScenario(
        scenario_id="s-1",
        network_model_id="n-1",
        candidate_bus_id="bus-1",
        evidence_cutoff="2026-01-01T00:00:00+00:00",
        horizon=StudyHorizon.DAY_AHEAD,
        requested_capacity_mw=50,
        minimum_viable_capacity_mw=30,
        power_factor=0.96,
        truth_class=TruthClass.SYNTHETIC_BENCHMARK,
        portfolio=portfolio(),
        evidence=(item or evidence(),),
        forecast_id="f-1",
        assumption_set_id="golden-v1",
    )


def provenance() -> RunProvenance:
    return RunProvenance(
        run_id="r-1",
        created_at="2026-01-01T01:00:00+00:00",
        evidence_cutoff="2026-01-01T00:00:00+00:00",
        code_version="test",
        assumption_set_id="golden-v1",
        solver_name="fixture",
        solver_version="1",
        input_hashes={"scenario": SHA},
        evidence=(evidence(),),
    )


def test_legacy_truth_aliases_are_normalized() -> None:
    assert coerce_truth_class("synthetic_benchmark_truth") is TruthClass.SYNTHETIC_BENCHMARK
    assert coerce_truth_class("synthetic_scenario") is TruthClass.SYNTHETIC_DEMONSTRATION
    with pytest.raises(ValueError, match="unknown truth class"):
        coerce_truth_class("probably-real")


def test_scenario_rejects_post_cutoff_evidence() -> None:
    value = scenario(item=evidence("2026-01-02T00:00:00+00:00"))
    with pytest.raises(ValueError, match="newer than its cutoff"):
        value.validate()


def test_network_envelope_rejects_n1_above_n0() -> None:
    value = NetworkEnvelope(
        envelope_id="n",
        network_model_id="n-1",
        candidate_bus_id="bus-1",
        timestamps=("2026-01-01T01:00:00+00:00",),
        n0_import_mw=(40,),
        n1_import_mw=(41,),
        truth_class=TruthClass.SYNTHETIC_BENCHMARK,
    )
    with pytest.raises(ValueError, match="N-1"):
        value.validate()


def test_synthetic_result_cannot_be_a_capacity_claim() -> None:
    value = CapacityEnvelopeResult(
        result_id="result-1",
        scenario_id="s-1",
        truth_class=TruthClass.SYNTHETIC_BENCHMARK,
        firm_capacity_mw=40,
        conditional_capacity_mw=45,
        activatable_capacity_mw=45,
        confidence_level=0.95,
        binding_constraint="line-1",
        unknown_constraints=(),
        capacity_claim=True,
        provenance=provenance(),
    )
    with pytest.raises(ValueError, match="cannot establish"):
        value.validate()


def test_contracts_serialize_with_versions_and_enum_values() -> None:
    assert scenario().as_dict()["truth_class"] == "synthetic_benchmark"
    assert provenance().as_dict()["schema_version"] == "gridpulse-run-provenance-v1"


def aligned_inputs():
    start = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    stamps = tuple((start + timedelta(hours=i)).isoformat() for i in range(3))
    forecast = ForecastDistribution(
        forecast_id="f-1",
        issued_at="2026-01-01T00:00:00+00:00",
        component="total_site_load",
        points=tuple(ForecastPoint(stamp, 40 + i, {"0.1": 38 + i, "0.9": 42 + i}) for i, stamp in enumerate(stamps)),
        model_version="golden-v1",
    )
    envelope = NetworkEnvelope(
        envelope_id="env-1",
        network_model_id="n-1",
        candidate_bus_id="bus-1",
        timestamps=stamps,
        n0_import_mw=(80, 80, 80),
        n1_import_mw=(60, 60, 60),
        truth_class=TruthClass.SYNTHETIC_BENCHMARK,
    )
    dispatch = DispatchTrajectory(
        points=tuple(DispatchPoint(stamp, 40 + i) for i, stamp in enumerate(stamps))
    )
    return forecast, envelope, dispatch
