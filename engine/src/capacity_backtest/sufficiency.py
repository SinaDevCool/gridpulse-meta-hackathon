"""Output-specific evidence sufficiency with explicit missing inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .contracts import SufficiencyStatus

REQUIREMENTS = {
    "constraint_screening": {
        "topology_identity",
        "congestion_or_loading_evidence",
        "temporal_coverage",
        "geographic_attribution",
    },
    "relative_node_ranking": {
        "consistent_topology",
        "comparable_demand_estimates",
        "voltage_equipment_context",
        "scenario_sensitivity_testing",
        "benchmark_validation",
    },
    "capacity_bands": {
        "electrical_parameters",
        "switching_state",
        "equipment_ratings",
        "existing_demand",
        "contracted_queued_demand",
        "generation_assumptions",
        "n_minus_one_policy",
        "operator_validation_or_outcomes",
    },
}


@dataclass(frozen=True)
class SufficiencyAssessment:
    output: str
    status: SufficiencyStatus
    present_inputs: list[str]
    missing_inputs: list[str]
    conclusion: str

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


def assess_sufficiency(output: str, available_inputs: set[str]) -> SufficiencyAssessment:
    required = REQUIREMENTS[output]
    present = sorted(required & available_inputs)
    missing = sorted(required - available_inputs)
    coverage = len(present) / len(required)
    if not missing:
        status = SufficiencyStatus.SUFFICIENT
    elif coverage >= 0.6:
        status = SufficiencyStatus.CONDITIONAL
    else:
        status = SufficiencyStatus.INSUFFICIENT
    conclusions = {
        "constraint_screening": "Constraint signals may be reported only at their published resolution.",
        "relative_node_ranking": "Ranking remains experimental until benchmark and outcome validation pass.",
        "capacity_bands": "Available MW cannot be published without every mandatory electrical and validation input.",
    }
    return SufficiencyAssessment(output, status, present, missing, conclusions[output])


def berlin_public_evidence_assessment() -> list[SufficiencyAssessment]:
    available = {
        "topology_identity",
        "congestion_or_loading_evidence",
        "temporal_coverage",
        "consistent_topology",
        "voltage_equipment_context",
        "generation_assumptions",
    }
    return [assess_sufficiency(output, available) for output in REQUIREMENTS]
