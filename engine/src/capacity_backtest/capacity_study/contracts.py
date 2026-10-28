"""Contracts for PCC hypotheses, network ensembles and capacity statistics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain.base import DomainContract, parse_aware_timestamp, require_non_empty
from capacity_backtest.domain.evidence import EvidenceReference


class PCCStatus(str, Enum):
    GEOGRAPHIC_HYPOTHESIS = "geographic_hypothesis"
    RECONSTRUCTED = "reconstructed"
    OPERATOR_PROPOSED = "operator_proposed"
    OPERATOR_CONFIRMED = "operator_confirmed"


class BlockerSeverity(str, Enum):
    INFORMATION = "information"
    SCREENING_LIMIT = "screening_limit"
    OPERATOR_CONFIRMATION_REQUIRED = "operator_confirmation_required"


@dataclass(frozen=True)
class CapacityBlocker(DomainContract):
    code: str
    severity: BlockerSeverity
    message: str
    resolvable_by: str

    def validate(self) -> None:
        for value, name in (
            (self.code, "code"),
            (self.message, "message"),
            (self.resolvable_by, "resolvable_by"),
        ):
            require_non_empty(value, name)


@dataclass(frozen=True)
class CandidatePCC(DomainContract):
    pcc_id: str
    bus_id: str
    operator_id: str
    voltage_kv: float
    latitude: float | None
    longitude: float | None
    distance_km: float | None
    status: PCCStatus
    confidence: float
    truth_class: TruthClass
    evidence: tuple[EvidenceReference, ...] = ()

    def validate(self) -> None:
        for value, name in (
            (self.pcc_id, "pcc_id"),
            (self.bus_id, "bus_id"),
            (self.operator_id, "operator_id"),
        ):
            require_non_empty(value, name)
        if self.voltage_kv <= 0 or not 0 <= self.confidence <= 1:
            raise ValueError("PCC voltage must be positive and confidence must lie in [0, 1]")
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValueError("invalid PCC latitude")
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValueError("invalid PCC longitude")
        if self.distance_km is not None and self.distance_km < 0:
            raise ValueError("PCC distance cannot be negative")
        truth = coerce_truth_class(self.truth_class)
        if self.status == PCCStatus.OPERATOR_CONFIRMED and truth != TruthClass.OPERATOR_CONFIRMED:
            raise ValueError("operator-confirmed PCC requires operator-confirmed truth")
        for item in self.evidence:
            item.validate()


@dataclass(frozen=True)
class OperatingStatePoint:
    timestamp: str
    background_load_mw: float
    background_generation_mw: float
    committed_connections_mw: float
    reservations_mw: float
    reactive_power_mvar: float
    active_outage_ids: tuple[str, ...] = ()
    switch_state_id: str = "base"
    tap_state_id: str = "base"

    def validate(self) -> None:
        parse_aware_timestamp(self.timestamp, "operating-state timestamp")
        if (
            min(
                self.background_load_mw,
                self.background_generation_mw,
                self.committed_connections_mw,
                self.reservations_mw,
            )
            < 0
        ):
            raise ValueError("operating-state powers cannot be negative")

    @property
    def net_committed_load_mw(self) -> float:
        return max(
            0.0,
            self.background_load_mw
            + self.committed_connections_mw
            + self.reservations_mw
            - self.background_generation_mw,
        )


@dataclass(frozen=True)
class OperatingStateSeries(DomainContract):
    series_id: str
    points: tuple[OperatingStatePoint, ...]
    truth_class: TruthClass
    evidence_cutoff: str
    reconstruction_method: str
    interval_hours: float

    def validate(self) -> None:
        require_non_empty(self.series_id, "series_id")
        require_non_empty(self.reconstruction_method, "reconstruction_method")
        parse_aware_timestamp(self.evidence_cutoff, "evidence_cutoff")
        if not self.points or self.interval_hours <= 0:
            raise ValueError("operating-state series requires points and positive interval")
        stamps = []
        for point in self.points:
            point.validate()
            stamp = parse_aware_timestamp(point.timestamp, "operating-state timestamp")
            stamps.append(stamp)
        if stamps != sorted(stamps) or len(stamps) != len(set(stamps)):
            raise ValueError("operating-state points must be unique and chronological")
        coerce_truth_class(self.truth_class)


@dataclass(frozen=True)
class NetworkModelRealization(DomainContract):
    realization_id: str
    network_model_id: str
    pcc: CandidatePCC
    probability_weight: float
    random_seed: int
    truth_class: TruthClass
    topology_version: str
    parameter_set_id: str
    assumptions: tuple[str, ...]
    model: object

    def validate(self) -> None:
        for value, name in (
            (self.realization_id, "realization_id"),
            (self.network_model_id, "network_model_id"),
            (self.topology_version, "topology_version"),
            (self.parameter_set_id, "parameter_set_id"),
        ):
            require_non_empty(value, name)
        self.pcc.validate()
        if self.probability_weight <= 0 or self.random_seed < 0:
            raise ValueError("realization weight must be positive and seed non-negative")
        coerce_truth_class(self.truth_class)


@dataclass(frozen=True)
class AvailabilityCapacity:
    availability: float
    capacity_mw: float


@dataclass(frozen=True)
class CapacityStatistics(DomainContract):
    firm_capacity_mw: float
    minimum_mw: float
    maximum_mw: float
    p10_mw: float
    p50_mw: float
    p90_mw: float
    availability_capacities: tuple[AvailabilityCapacity, ...]
    duration_curve_mw: tuple[float, ...]
    requested_capacity_mw: float
    curtailment_hours: float
    curtailed_mwh: float
    curtailment_event_count: int
    maximum_event_hours: float
    binding_constraint_counts: dict[str, int]
    failed_realization_fraction: float
    lower_bound_realization_fraction: float

    def validate(self) -> None:
        values = (
            self.firm_capacity_mw,
            self.minimum_mw,
            self.maximum_mw,
            self.p10_mw,
            self.p50_mw,
            self.p90_mw,
        )
        if any(value < 0 for value in values) or self.requested_capacity_mw <= 0:
            raise ValueError("capacity statistics must be non-negative")
        if not self.minimum_mw <= self.firm_capacity_mw <= self.maximum_mw:
            raise ValueError("firm capacity must lie inside observed bounds")
        if (
            not 0 <= self.failed_realization_fraction <= 1
            or not 0 <= self.lower_bound_realization_fraction <= 1
        ):
            raise ValueError("realization fractions must lie in [0, 1]")
        if any(
            not 0 < item.availability <= 1 or item.capacity_mw < 0
            for item in self.availability_capacities
        ):
            raise ValueError("invalid availability-qualified capacity")
