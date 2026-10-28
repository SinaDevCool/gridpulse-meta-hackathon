"""Build one governed capacity-envelope assessment from Phase 1 evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from capacity_backtest.contracts import coerce_truth_class
from capacity_backtest.domain import CapacityEnvelopeResult, RunProvenance, StudyScenario

from .ac_envelope import ACEnvelopeStudy

PHASE1_CAPACITY_SCHEMA_VERSION = "gridpulse-phase1-capacity-assessment-v1"


@dataclass(frozen=True)
class OperatingConditions:
    confidence_level: float
    maximum_event_hours: int
    annual_constrained_hours: int
    required_resource_ids: tuple[str, ...]
    policy: str

    def validate(self) -> None:
        if not 0 < self.confidence_level < 1:
            raise ValueError("operating confidence must lie in (0, 1)")
        if self.maximum_event_hours < 0 or self.annual_constrained_hours < 0:
            raise ValueError("operating event limits cannot be negative")
        if len(self.required_resource_ids) != len(set(self.required_resource_ids)):
            raise ValueError("required resource identifiers must be unique")
        if not self.policy:
            raise ValueError("operating policy is required")


@dataclass(frozen=True)
class Phase1CapacityAssessment:
    result: CapacityEnvelopeResult
    operating_conditions: OperatingConditions
    chronological_firm_envelope_mw: tuple[float, ...]
    chronological_conditional_envelope_mw: tuple[float, ...]
    risk_metrics: dict[str, float | int | bool]
    schema_version: str = PHASE1_CAPACITY_SCHEMA_VERSION

    def validate(self) -> None:
        self.result.validate()
        self.operating_conditions.validate()
        if not self.chronological_firm_envelope_mw:
            raise ValueError("capacity assessment requires a chronological envelope")
        if len(self.chronological_firm_envelope_mw) != len(
            self.chronological_conditional_envelope_mw
        ):
            raise ValueError("firm and conditional envelopes must align")
        if any(
            conditional + 1e-9 < firm
            for firm, conditional in zip(
                self.chronological_firm_envelope_mw,
                self.chronological_conditional_envelope_mw,
            )
        ):
            raise ValueError("conditional envelope cannot be below firm envelope")


def build_capacity_assessment(
    scenario: StudyScenario,
    ac_study: ACEnvelopeStudy,
    risk_backtest: dict[str, object],
    provenance: RunProvenance,
    *,
    maximum_event_hours: int,
    annual_constrained_hours: int,
) -> Phase1CapacityAssessment:
    """Conservatively combine physics and held-out policy evidence without making a claim."""

    scenario.validate()
    ac_study.envelope.validate()
    provenance.validate()
    if not ac_study.physics_verified:
        raise ValueError("Phase 1 capacity assessment requires physics verification")
    if scenario.network_model_id != ac_study.envelope.network_model_id:
        raise ValueError("scenario and AC study network identities do not match")
    if scenario.candidate_bus_id != ac_study.envelope.candidate_bus_id:
        raise ValueError("scenario and AC study candidate buses do not match")
    if risk_backtest.get("schema_version") != "gridpulse-risk-limiting-backtest-v1":
        raise ValueError("unsupported risk backtest")
    recommended_name = str(risk_backtest.get("recommended_policy", ""))
    rows = cast(list[dict[str, Any]], risk_backtest.get("results", []))
    recommended = next((row for row in rows if row.get("policy") == recommended_name), None)
    if recommended is None or recommended.get("oracle") is True:
        raise ValueError("capacity assessment requires a non-oracle recommended policy")
    admitted = tuple(float(value) for value in recommended["admitted_capacity_mw"])
    if len(admitted) != len(ac_study.envelope.timestamps):
        raise ValueError("risk policy and AC envelope must be chronological and aligned")
    firm_series = tuple(ac_study.envelope.n1_import_mw)
    conditional_series = tuple(
        max(firm, min(n0, allowed))
        for firm, n0, allowed in zip(firm_series, ac_study.envelope.n0_import_mw, admitted)
    )
    firm = min(firm_series)
    # A scalar capacity without an explicit availability level must be supportable
    # throughout the assessed chronology. Higher conditional levels are reported by
    # the duration-curve aggregator, never by taking the maximum observed interval.
    conditional = min(conditional_series)
    activatable = min(scenario.requested_capacity_mw, conditional)
    binding = min(ac_study.states, key=lambda row: row.n1_import_mw)
    truth = coerce_truth_class(ac_study.envelope.truth_class)
    result = CapacityEnvelopeResult(
        result_id=f"phase1-{scenario.scenario_id}",
        scenario_id=scenario.scenario_id,
        truth_class=truth,
        firm_capacity_mw=firm,
        conditional_capacity_mw=conditional,
        activatable_capacity_mw=activatable,
        confidence_level=float(cast(float, risk_backtest["confidence"])),
        binding_constraint=binding.binding_constraint,
        unknown_constraints=ac_study.limitations,
        capacity_claim=False,
        provenance=provenance,
    )
    conditions = OperatingConditions(
        confidence_level=float(cast(float, risk_backtest["confidence"])),
        maximum_event_hours=maximum_event_hours,
        annual_constrained_hours=annual_constrained_hours,
        required_resource_ids=tuple(
            resource.resource_id for resource in scenario.portfolio.resources
        ),
        policy=recommended_name,
    )
    assessment = Phase1CapacityAssessment(
        result=result,
        operating_conditions=conditions,
        chronological_firm_envelope_mw=firm_series,
        chronological_conditional_envelope_mw=conditional_series,
        risk_metrics={
            "unsafe_overstatement_hours": int(recommended["unsafe_overstatement_hours"]),
            "violation_probability": float(recommended["violation_probability"]),
            "unserved_mwh": float(recommended["unserved_mwh"]),
            "calibration_error": float(recommended["calibration_error"]),
            "release_gate_passed": bool(risk_backtest["release_gate_passed"]),
        },
    )
    assessment.validate()
    return assessment
