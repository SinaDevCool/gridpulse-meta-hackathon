"""Event-driven stale-envelope detection and recalculation routing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from capacity_backtest.domain.base import parse_aware_timestamp


class EventKind(str, Enum):
    OUTAGE = "outage"
    OUTAGE_REVISION = "outage_revision"
    FORECAST_VINTAGE = "forecast_vintage"
    SOC_DEVIATION = "soc_deviation"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    RESERVATION_CHANGE = "reservation_change"
    NETWORK_MODEL_REVISION = "network_model_revision"
    MEASUREMENT_QUALITY = "measurement_quality"
    OPERATOR_CONSTRAINT = "operator_constraint"


@dataclass(frozen=True)
class RecalculationEvent:
    event_id: str
    kind: EventKind
    published_at: str
    network_model_id: str | None = None
    candidate_bus_id: str | None = None
    resource_id: str | None = None
    forecast_id: str | None = None
    material: bool = True

    def validate(self) -> None:
        if not self.event_id:
            raise ValueError("recalculation event_id is required")
        parse_aware_timestamp(self.published_at, "event published_at")


@dataclass(frozen=True)
class EnvelopeRegistration:
    result_id: str
    calculated_at: str
    network_model_id: str
    candidate_bus_id: str
    forecast_id: str
    resource_ids: tuple[str, ...]


@dataclass(frozen=True)
class InvalidationDecision:
    result_id: str
    stale: bool
    reasons: tuple[str, ...]
    earliest_event_at: str | None


class RecalculationRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, EnvelopeRegistration] = {}
        self._events: dict[str, RecalculationEvent] = {}

    def register(self, value: EnvelopeRegistration) -> None:
        parse_aware_timestamp(value.calculated_at, "calculated_at")
        if not value.result_id or value.result_id in self._registrations:
            raise ValueError("result registration identity must be unique")
        self._registrations[value.result_id] = value

    def publish(self, event: RecalculationEvent) -> None:
        event.validate()
        current = self._events.get(event.event_id)
        if current and current != event:
            raise ValueError("event identifiers are immutable")
        self._events[event.event_id] = event

    def decision(self, result_id: str) -> InvalidationDecision:
        registration = self._registrations.get(result_id)
        if registration is None:
            raise ValueError("unknown registered result")
        calculated = parse_aware_timestamp(registration.calculated_at, "calculated_at")
        matching = []
        for event in self._events.values():
            published = parse_aware_timestamp(event.published_at, "event published_at")
            if not event.material or published <= calculated:
                continue
            applies = (
                (event.network_model_id is None or event.network_model_id == registration.network_model_id)
                and (event.candidate_bus_id is None or event.candidate_bus_id == registration.candidate_bus_id)
                and (event.resource_id is None or event.resource_id in registration.resource_ids)
                and (event.forecast_id is None or event.forecast_id == registration.forecast_id)
            )
            if applies:
                matching.append(event)
        matching.sort(key=lambda item: item.published_at)
        return InvalidationDecision(
            result_id, bool(matching), tuple(f"{item.kind.value}:{item.event_id}" for item in matching),
            matching[0].published_at if matching else None,
        )
