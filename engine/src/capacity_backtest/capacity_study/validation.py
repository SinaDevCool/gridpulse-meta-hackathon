"""Hidden-data reconstruction validation metrics for SimBench and operator cases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReconstructionCase:
    case_id: str
    true_capacity_mw: float
    p10_mw: float
    p50_mw: float
    p90_mw: float
    true_binding_constraint: str
    predicted_binding_constraint: str
    abstained: bool = False


def evaluate_reconstruction(cases: list[ReconstructionCase]) -> dict[str, object]:
    evaluated = [case for case in cases if not case.abstained]
    if not cases or not evaluated:
        raise ValueError("reconstruction validation requires evaluated cases")
    errors = [abs(case.p50_mw - case.true_capacity_mw) for case in evaluated]
    covered = [case.p10_mw <= case.true_capacity_mw <= case.p90_mw for case in evaluated]
    severe = [case.p50_mw > case.true_capacity_mw * 1.2 for case in evaluated]
    binding = [
        case.true_binding_constraint == case.predicted_binding_constraint for case in evaluated
    ]
    interval_coverage = sum(covered) / len(covered)
    severe_overstatement_rate = sum(severe) / len(severe)
    binding_constraint_accuracy = sum(binding) / len(binding)
    release_gate_passed = (
        interval_coverage >= 0.8
        and severe_overstatement_rate <= 0.05
        and binding_constraint_accuracy >= 0.7
    )
    metrics: dict[str, object] = {
        "schema_version": "gridpulse-reconstruction-validation-v1",
        "case_count": len(cases),
        "evaluated_count": len(evaluated),
        "mae_mw": sum(errors) / len(errors),
        "interval_coverage": interval_coverage,
        "severe_overstatement_rate": severe_overstatement_rate,
        "binding_constraint_accuracy": binding_constraint_accuracy,
        "abstention_rate": 1 - len(evaluated) / len(cases),
    }
    metrics["release_gate_passed"] = release_gate_passed
    return metrics
