"""Four-layer Grid Care AI output contract with non-promotable truth classes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GridCareOutput:
    public_constraint_context: dict[str, Any]
    probabilistic_regional_risk: dict[str, Any]
    synthetic_flexibility_study: dict[str, Any]
    operator_confirmed_capacity: dict[str, Any]

    def validate(self) -> None:
        expected = {
            "public_constraint_context": "operator_published_context",
            "probabilistic_regional_risk": "experimental_estimate",
            "synthetic_flexibility_study": "synthetic_benchmark",
            "operator_confirmed_capacity": "unavailable",
        }
        for name, truth_class in expected.items():
            layer = getattr(self, name)
            if layer.get("truth_class") != truth_class:
                raise ValueError(f"{name} has an invalid truth class")
        confirmed = self.operator_confirmed_capacity
        if confirmed.get("available_capacity_mw") is not None:
            raise ValueError("operator-confirmed capacity is unavailable without operator evidence")
        if self.synthetic_flexibility_study.get("capacity_claim") is not False:
            raise ValueError("synthetic flexibility must explicitly reject a capacity claim")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": "grid-care-ai-output-v1",
            "layers": {
                "public_constraint_context": self.public_constraint_context,
                "probabilistic_regional_risk": self.probabilistic_regional_risk,
                "synthetic_flexibility_study": self.synthetic_flexibility_study,
                "operator_confirmed_capacity": self.operator_confirmed_capacity,
            },
            "layers_blended": False,
        }


def unavailable_gridcare_output() -> GridCareOutput:
    return GridCareOutput(
        public_constraint_context={
            "truth_class": "operator_published_context",
            "message": "Published upstream constraint context may be shown at source resolution.",
            "available_capacity_mw": None,
        },
        probabilistic_regional_risk={
            "truth_class": "experimental_estimate",
            "release_gate_passed": False,
            "message": "Experimental regional risk; operational release is blocked.",
            "available_capacity_mw": None,
        },
        synthetic_flexibility_study={
            "truth_class": "synthetic_benchmark",
            "capacity_claim": False,
            "message": "Synthetic network and flexibility mechanics only.",
            "available_capacity_mw": None,
        },
        operator_confirmed_capacity={
            "truth_class": "unavailable",
            "available_capacity_mw": None,
            "message": "Operator evidence required.",
        },
    )
