"""Role-specific source quality, independent from capacity or site suitability."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .contracts import SourceDefinition


@dataclass(frozen=True)
class QualityAssessment:
    source_id: str
    intended_role: str
    authority: int
    geographic_specificity: int
    temporal_freshness: int
    electrical_specificity: int
    completeness: int
    reproducibility: int
    licence_clarity: int
    usable: bool
    limitations: list[str]

    @property
    def score(self) -> float:
        fields = (
            self.authority,
            self.geographic_specificity,
            self.temporal_freshness,
            self.electrical_specificity,
            self.completeness,
            self.reproducibility,
            self.licence_clarity,
        )
        return round(sum(fields) / (len(fields) * 5) * 100, 1)

    def as_dict(self) -> dict[str, object]:
        return {**asdict(self), "score": self.score}


def assess_source(source: SourceDefinition, intended_role: str) -> QualityAssessment:
    authority = {"operator": 5, "regulator": 5, "operator_portal": 4, "research_benchmark": 4, "public_mapping": 2}.get(source.authority, 1)
    geographic = 5 if "Berlin" in source.coverage else 3 if "Germany" in source.coverage else 2
    electrical = 4 if source.voltage_scope else 2
    role_match = intended_role in source.purposes
    limitations = [f"Not suitable for {item}." for item in source.prohibited_uses]
    return QualityAssessment(
        source.id,
        intended_role,
        authority,
        geographic,
        4,
        electrical,
        3,
        4,
        3,
        role_match and authority >= 3,
        limitations,
    )
