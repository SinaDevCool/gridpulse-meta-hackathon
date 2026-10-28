"""Single fail-closed orchestration boundary for capacity studies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import TruthClass, coerce_truth_class
from .domain import (
    CapacityEnvelopeResult,
    DispatchTrajectory,
    ForecastDistribution,
    NetworkEnvelope,
    RunProvenance,
    StudyScenario,
)

PIPELINE_SCHEMA_VERSION = "gridpulse-study-pipeline-v1"
CAPACITY_STUDY_PIPELINE_SCHEMA_VERSION = "gridpulse-capacity-study-pipeline-v2"


class NetworkScreen(Protocol):
    def __call__(
        self, scenario: StudyScenario, forecast: ForecastDistribution, envelope: NetworkEnvelope
    ) -> dict[str, object]: ...


class DetailedNetworkVerifier(Protocol):
    def __call__(
        self,
        scenario: StudyScenario,
        forecast: ForecastDistribution,
        envelope: NetworkEnvelope,
        screening: dict[str, object],
    ) -> dict[str, object]: ...


class DispatchOptimizer(Protocol):
    def __call__(
        self,
        scenario: StudyScenario,
        forecast: ForecastDistribution,
        envelope: NetworkEnvelope,
        verification: dict[str, object],
    ) -> DispatchTrajectory: ...


class ResultBuilder(Protocol):
    def __call__(
        self,
        scenario: StudyScenario,
        envelope: NetworkEnvelope,
        verification: dict[str, object],
        dispatch: DispatchTrajectory,
        provenance: RunProvenance,
    ) -> CapacityEnvelopeResult: ...


class CapacityStudyPrepare(Protocol):
    def __call__(self) -> dict[str, Any]: ...


class CapacityStudyScreen(Protocol):
    def __call__(self, prepared: dict[str, Any]) -> dict[str, Any]: ...


class CapacityStudyVerify(Protocol):
    def __call__(
        self, prepared: dict[str, Any], screening: dict[str, Any]
    ) -> dict[str, Any]: ...


class CapacityStudyAggregate(Protocol):
    def __call__(
        self,
        prepared: dict[str, Any],
        screening: dict[str, Any],
        verification: dict[str, Any],
    ) -> dict[str, Any]: ...


class CapacityStudyResultBuilder(Protocol):
    def __call__(
        self,
        prepared: dict[str, Any],
        screening: dict[str, Any],
        verification: dict[str, Any],
        aggregation: dict[str, Any],
    ) -> Any: ...


@dataclass(frozen=True)
class PipelineStages:
    screen: NetworkScreen
    verify: DetailedNetworkVerifier
    optimize: DispatchOptimizer
    build_result: ResultBuilder


@dataclass(frozen=True)
class CapacityStudyPipelineStages:
    """Ordered adapters for ensemble and multi-PCC capacity studies."""

    prepare: Callable[[], dict[str, Any]]
    screen: Callable[[dict[str, Any]], dict[str, Any]]
    verify: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    aggregate: Callable[
        [dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]
    ]
    build_result: Callable[
        [dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], Any
    ]


@dataclass(frozen=True)
class CapacityStudyPipelineRun:
    prepared: dict[str, Any]
    screening: dict[str, Any]
    verification: dict[str, Any]
    aggregation: dict[str, Any]
    result: Any
    schema_version: str = CAPACITY_STUDY_PIPELINE_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        result = self.result.as_dict() if hasattr(self.result, "as_dict") else self.result
        return {
            "schema_version": self.schema_version,
            "prepared": self.prepared,
            "screening": self.screening,
            "verification": self.verification,
            "aggregation": self.aggregation,
            "result": result,
        }

    def fingerprint(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PipelineRun:
    scenario: StudyScenario
    forecast: ForecastDistribution
    envelope: NetworkEnvelope
    screening: dict[str, object]
    verification: dict[str, object]
    dispatch: DispatchTrajectory
    result: CapacityEnvelopeResult
    schema_version: str = PIPELINE_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario": self.scenario.as_dict(),
            "forecast": self.forecast.as_dict(),
            "network_envelope": self.envelope.as_dict(),
            "screening": self.screening,
            "verification": self.verification,
            "dispatch": self.dispatch.as_dict(),
            "result": self.result.as_dict(),
        }

    def fingerprint(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class StudyPipeline:
    """Validate and execute the canonical screen → verify → optimize → result flow."""

    def __init__(self, stages: PipelineStages):
        self.stages = stages

    @classmethod
    def run_capacity_study(
        cls, stages: CapacityStudyPipelineStages
    ) -> CapacityStudyPipelineRun:
        """Run the v2 prepare -> screen -> verify -> aggregate -> result workflow."""

        prepared = stages.prepare()
        if prepared.get("evidence_validated") is not True:
            raise ValueError("capacity studies fail closed without evidence validation")
        screening = stages.screen(prepared)
        if screening.get("requires_detailed_verification") is not True:
            raise ValueError("screening must require detailed network verification")
        verification = stages.verify(prepared, screening)
        if verification.get("physics_verified") is not True:
            raise ValueError("capacity studies fail closed without physics verification")
        aggregation = stages.aggregate(prepared, screening, verification)
        if aggregation.get("pcc_isolation_verified") is not True:
            raise ValueError("capacity aggregation must remain isolated by PCC")
        result = stages.build_result(prepared, screening, verification, aggregation)
        if hasattr(result, "validate"):
            result.validate()
        return CapacityStudyPipelineRun(
            prepared=prepared,
            screening=screening,
            verification=verification,
            aggregation=aggregation,
            result=result,
        )

    def run(
        self,
        scenario: StudyScenario,
        forecast: ForecastDistribution,
        envelope: NetworkEnvelope,
        provenance: RunProvenance,
    ) -> PipelineRun:
        scenario.validate()
        forecast.validate()
        envelope.validate()
        provenance.validate()
        self._validate_alignment(scenario, forecast, envelope, provenance)
        screening = self.stages.screen(scenario, forecast, envelope)
        if screening.get("requires_detailed_verification") is not True:
            raise ValueError("screening must require detailed network verification")
        verification = self.stages.verify(scenario, forecast, envelope, screening)
        if verification.get("physics_verified") is not True:
            raise ValueError("capacity studies fail closed without physics verification")
        dispatch = self.stages.optimize(scenario, forecast, envelope, verification)
        dispatch.validate()
        result = self.stages.build_result(
            scenario, envelope, verification, dispatch, provenance
        )
        result.validate()
        if result.scenario_id != scenario.scenario_id:
            raise ValueError("result scenario identity does not match pipeline input")
        if result.provenance.fingerprint() != provenance.fingerprint():
            raise ValueError("result provenance does not match pipeline input")
        scenario_truth = coerce_truth_class(scenario.truth_class)
        envelope_truth = coerce_truth_class(envelope.truth_class)
        result_truth = coerce_truth_class(result.truth_class)
        if TruthClass.OPERATOR_CONFIRMED not in {
            scenario_truth,
            envelope_truth,
        } and (result_truth == TruthClass.OPERATOR_CONFIRMED or result.capacity_claim):
            raise ValueError("non-operator inputs cannot be promoted to a capacity claim")
        return PipelineRun(
            scenario=scenario,
            forecast=forecast,
            envelope=envelope,
            screening=screening,
            verification=verification,
            dispatch=dispatch,
            result=result,
        )

    @staticmethod
    def _validate_alignment(
        scenario: StudyScenario,
        forecast: ForecastDistribution,
        envelope: NetworkEnvelope,
        provenance: RunProvenance,
    ) -> None:
        if scenario.forecast_id != forecast.forecast_id:
            raise ValueError("scenario and forecast identities do not match")
        if scenario.network_model_id != envelope.network_model_id:
            raise ValueError("scenario and network model identities do not match")
        if scenario.candidate_bus_id != envelope.candidate_bus_id:
            raise ValueError("scenario and envelope candidate buses do not match")
        forecast_timestamps = tuple(point.timestamp for point in forecast.points)
        if forecast_timestamps != envelope.timestamps:
            raise ValueError("forecast and network-envelope timestamps must align exactly")
        if scenario.evidence_cutoff != provenance.evidence_cutoff:
            raise ValueError("scenario and provenance evidence cutoffs do not match")
