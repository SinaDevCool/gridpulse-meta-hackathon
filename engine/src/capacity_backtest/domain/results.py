"""Canonical capacity-envelope and dispatch result contracts."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.contracts import (
    TruthClass,
    assert_capacity_claim_allowed,
    coerce_truth_class,
)

from .base import DomainContract, parse_aware_timestamp, require_non_empty
from .evidence import RunProvenance

DISPATCH_SCHEMA_VERSION = "gridpulse-dispatch-trajectory-v1"
CAPACITY_RESULT_SCHEMA_VERSION = "gridpulse-capacity-envelope-result-v1"


@dataclass(frozen=True)
class DispatchPoint:
    timestamp: str
    grid_import_mw: float
    curtailed_mw: float = 0.0
    battery_soc_mwh: float | None = None
    unserved_mw: float = 0.0

    def validate(self) -> None:
        parse_aware_timestamp(self.timestamp, "dispatch timestamp")
        if min(self.grid_import_mw, self.curtailed_mw, self.unserved_mw) < 0:
            raise ValueError("dispatch powers cannot be negative")
        if self.battery_soc_mwh is not None and self.battery_soc_mwh < 0:
            raise ValueError("battery SOC cannot be negative")


@dataclass(frozen=True)
class DispatchTrajectory(DomainContract):
    points: tuple[DispatchPoint, ...]
    schema_version: str = DISPATCH_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != DISPATCH_SCHEMA_VERSION or not self.points:
            raise ValueError("dispatch trajectory must use the supported schema and contain points")
        parsed = []
        for point in self.points:
            point.validate()
            parsed.append(parse_aware_timestamp(point.timestamp, "dispatch timestamp"))
        if parsed != sorted(parsed) or len(parsed) != len(set(parsed)):
            raise ValueError("dispatch points must be unique and chronological")


@dataclass(frozen=True)
class CapacityEnvelopeResult(DomainContract):
    result_id: str
    scenario_id: str
    truth_class: TruthClass
    firm_capacity_mw: float | None
    conditional_capacity_mw: float | None
    activatable_capacity_mw: float | None
    confidence_level: float | None
    binding_constraint: str | None
    unknown_constraints: tuple[str, ...]
    capacity_claim: bool
    provenance: RunProvenance
    dispatch: DispatchTrajectory | None = None
    schema_version: str = CAPACITY_RESULT_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != CAPACITY_RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported capacity-envelope result schema")
        require_non_empty(self.result_id, "result_id")
        require_non_empty(self.scenario_id, "scenario_id")
        truth = coerce_truth_class(self.truth_class)
        values = (self.firm_capacity_mw, self.conditional_capacity_mw, self.activatable_capacity_mw)
        if any(value is not None and value < 0 for value in values):
            raise ValueError("capacity values cannot be negative")
        if self.confidence_level is not None and not 0 < self.confidence_level <= 1:
            raise ValueError("confidence_level must be in (0, 1]")
        if self.capacity_claim:
            if self.firm_capacity_mw is None:
                raise ValueError("a capacity claim requires firm_capacity_mw")
            assert_capacity_claim_allowed(truth, self.firm_capacity_mw)
        elif truth != TruthClass.OPERATOR_CONFIRMED:
            assert_capacity_claim_allowed(truth, None)
        self.provenance.validate()
        if self.dispatch is not None:
            self.dispatch.validate()
