"""Technical areas, congestion and reinforcement context models."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .contracts import TruthClass


@dataclass(frozen=True)
class TechnicalArea:
    area_id: str
    name: str
    node_ids: list[str]
    allocated_mva: float | None
    publication_year: int
    boundary_type: str
    mapping_confidence: str
    source_reference: str
    remaining_mva: None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReinforcementProject:
    project_id: str
    operator: str
    project_name: str
    asset_type: str
    voltage_kv: float | None
    location: str | None
    affected_nodes: list[str]
    status: str
    planned_commissioning_date: str | None
    published_effect: str | None
    source_reference: str
    truth_class: TruthClass = TruthClass.PLANNED_REINFORCEMENT


@dataclass(frozen=True)
class CongestionEvent:
    start: str
    end: str
    operator: str
    affected_element: str | None
    direction: str | None
    redispatch_mwh: float | None
    curtailment_mwh: float | None
    cause: str | None
    resolution: str
    source_reference: str
    truth_class: TruthClass = TruthClass.CONSTRAINT_DETECTED


def congestion_summary(events: list[CongestionEvent]) -> dict[str, object]:
    return {
        "event_count": len(events),
        "redispatch_mwh": sum(event.redispatch_mwh or 0 for event in events),
        "curtailment_mwh": sum(event.curtailment_mwh or 0 for event in events),
        "specific_element_events": sum(event.resolution == "specific_network_element" for event in events),
        "limitations": [
            "Congestion is a constraint signal, not available connection capacity.",
            "Control-area events must not be assigned to individual Berlin substations.",
        ],
    }


def validate_reinforcement(project: ReinforcementProject) -> None:
    if project.status not in {"proposed", "permitting", "under_construction", "commissioned", "delayed", "unknown"}:
        raise ValueError("invalid reinforcement status")
    if project.status != "commissioned" and project.published_effect:
        # Published future effect remains context and cannot become current capacity.
        return
