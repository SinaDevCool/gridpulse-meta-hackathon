from __future__ import annotations

import pytest

from capacity_backtest.contracts import TruthClass
from capacity_backtest.domain import CapacityEnvelopeResult
from capacity_backtest.pipeline import CapacityStudyPipelineStages, PipelineStages, StudyPipeline

from .test_phase0_domain import aligned_inputs, provenance, scenario


def stages(*, verified: bool = True, claim: bool = False) -> PipelineStages:
    def screen(_scenario, _forecast, _envelope):
        return {"requires_detailed_verification": True, "screened": True}

    def verify(_scenario, _forecast, _envelope, _screening):
        return {"physics_verified": verified, "binding_constraint": "n-1-security"}

    def optimize(_scenario, _forecast, _envelope, _verification):
        return aligned_inputs()[2]

    def build_result(_scenario, _envelope, verification, dispatch, run_provenance):
        return CapacityEnvelopeResult(
            result_id="result-1",
            scenario_id="s-1",
            truth_class=TruthClass.OPERATOR_CONFIRMED if claim else TruthClass.SYNTHETIC_BENCHMARK,
            firm_capacity_mw=50,
            conditional_capacity_mw=55,
            activatable_capacity_mw=55,
            confidence_level=0.95,
            binding_constraint=str(verification["binding_constraint"]),
            unknown_constraints=("operator protection settings",),
            capacity_claim=claim,
            provenance=run_provenance,
            dispatch=dispatch,
        )

    return PipelineStages(screen, verify, optimize, build_result)


def test_pipeline_runs_all_stages_and_is_deterministically_fingerprinted() -> None:
    forecast, envelope, _ = aligned_inputs()
    pipeline = StudyPipeline(stages())
    first = pipeline.run(scenario(), forecast, envelope, provenance())
    second = pipeline.run(scenario(), forecast, envelope, provenance())
    assert first.result.capacity_claim is False
    assert first.fingerprint() == second.fingerprint()


def test_pipeline_fails_closed_without_physics_verification() -> None:
    forecast, envelope, _ = aligned_inputs()
    with pytest.raises(ValueError, match="physics verification"):
        StudyPipeline(stages(verified=False)).run(scenario(), forecast, envelope, provenance())


def test_pipeline_cannot_promote_synthetic_inputs_to_operator_claim() -> None:
    forecast, envelope, _ = aligned_inputs()
    with pytest.raises(ValueError, match="cannot establish|cannot be promoted"):
        StudyPipeline(stages(claim=True)).run(scenario(), forecast, envelope, provenance())


def test_pipeline_rejects_misaligned_forecast() -> None:
    forecast, envelope, _ = aligned_inputs()
    object.__setattr__(forecast, "forecast_id", "different")
    with pytest.raises(ValueError, match="identities do not match"):
        StudyPipeline(stages()).run(scenario(), forecast, envelope, provenance())


def capacity_study_stages(*, verified: bool = True, isolated: bool = True):
    class Result:
        def validate(self):
            return None

        def as_dict(self):
            return {"capacity_claim": False}

    return CapacityStudyPipelineStages(
        prepare=lambda: {"evidence_validated": True},
        screen=lambda _prepared: {"requires_detailed_verification": True},
        verify=lambda _prepared, _screening: {"physics_verified": verified},
        aggregate=lambda _prepared, _screening, _verification: {
            "pcc_isolation_verified": isolated
        },
        build_result=lambda _prepared, _screening, _verification, _aggregation: Result(),
    )


def test_capacity_study_pipeline_v2_enforces_physics_and_pcc_isolation() -> None:
    with pytest.raises(ValueError, match="physics verification"):
        StudyPipeline.run_capacity_study(capacity_study_stages(verified=False))
    with pytest.raises(ValueError, match="isolated by PCC"):
        StudyPipeline.run_capacity_study(capacity_study_stages(isolated=False))
    result = StudyPipeline.run_capacity_study(capacity_study_stages())
    assert result.as_dict()["result"]["capacity_claim"] is False
