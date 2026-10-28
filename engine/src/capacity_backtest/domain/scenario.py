"""Canonical input scenario for every capacity study implementation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from capacity_backtest.contracts import TruthClass, coerce_truth_class

from .base import DomainContract, parse_aware_timestamp, require_non_empty
from .evidence import EvidenceReference
from .resources import FlexibilityPortfolio

SCENARIO_SCHEMA_VERSION = "gridpulse-study-scenario-v1"


class StudyHorizon(str, Enum):
    DAY_AHEAD = "day_ahead"
    WEEK_AHEAD = "week_ahead"
    SEASONAL = "seasonal"
    CONNECTION_PLANNING = "connection_planning"


@dataclass(frozen=True)
class StudyScenario(DomainContract):
    scenario_id: str
    network_model_id: str
    candidate_bus_id: str
    evidence_cutoff: str
    horizon: StudyHorizon
    requested_capacity_mw: float
    minimum_viable_capacity_mw: float
    power_factor: float
    truth_class: TruthClass
    portfolio: FlexibilityPortfolio
    evidence: tuple[EvidenceReference, ...]
    forecast_id: str
    assumption_set_id: str
    site_location_id: str | None = None
    territory_match_id: str | None = None
    responsibility_result_id: str | None = None
    operator_confirmation_id: str | None = None
    candidate_pcc_evidence_id: str | None = None
    schema_version: str = SCENARIO_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != SCENARIO_SCHEMA_VERSION:
            raise ValueError("unsupported study-scenario schema")
        for value, name in (
            (self.scenario_id, "scenario_id"),
            (self.network_model_id, "network_model_id"),
            (self.candidate_bus_id, "candidate_bus_id"),
            (self.forecast_id, "forecast_id"),
            (self.assumption_set_id, "assumption_set_id"),
        ):
            require_non_empty(value, name)
        cutoff = parse_aware_timestamp(self.evidence_cutoff, "evidence_cutoff")
        if self.requested_capacity_mw <= 0:
            raise ValueError("requested_capacity_mw must be positive")
        if not 0 <= self.minimum_viable_capacity_mw <= self.requested_capacity_mw:
            raise ValueError("minimum viable capacity must be within the request")
        if not 0 < self.power_factor <= 1:
            raise ValueError("power_factor must be in (0, 1]")
        coerce_truth_class(self.truth_class)
        self.portfolio.validate()
        for item in self.evidence:
            item.validate()
            if parse_aware_timestamp(item.retrieved_at, "retrieved_at") > cutoff:
                raise ValueError("scenario contains evidence newer than its cutoff")
        territory_refs = (
            self.site_location_id,
            self.territory_match_id,
            self.responsibility_result_id,
        )
        if any(territory_refs) and not all(territory_refs):
            raise ValueError("real-site scenario requires location, territory, and responsibility references")
        if self.candidate_pcc_evidence_id and not self.operator_confirmation_id:
            raise ValueError("candidate PCC evidence requires operator confirmation")
