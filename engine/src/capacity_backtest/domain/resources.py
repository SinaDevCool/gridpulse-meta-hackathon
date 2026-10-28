"""Customer-side flexibility resource contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .base import DomainContract, require_non_empty

RESOURCE_SCHEMA_VERSION = "gridpulse-flexibility-portfolio-v1"


class ResourceKind(str, Enum):
    BATTERY = "battery"
    FLEXIBLE_WORKLOAD = "flexible_workload"
    COOLING = "cooling"
    ONSITE_GENERATION = "onsite_generation"


@dataclass(frozen=True)
class FlexibilityResource:
    resource_id: str
    kind: ResourceKind
    power_mw: float
    energy_mwh: float | None = None
    availability_probability: float = 1.0
    response_seconds: float = 0.0
    minimum_reserve_fraction: float = 0.0

    def validate(self) -> None:
        require_non_empty(self.resource_id, "resource_id")
        if self.power_mw < 0 or self.response_seconds < 0:
            raise ValueError("resource power and response time cannot be negative")
        if self.energy_mwh is not None and self.energy_mwh < 0:
            raise ValueError("resource energy cannot be negative")
        if not 0 <= self.availability_probability <= 1:
            raise ValueError("availability_probability must be in [0, 1]")
        if not 0 <= self.minimum_reserve_fraction <= 1:
            raise ValueError("minimum_reserve_fraction must be in [0, 1]")
        if self.kind == ResourceKind.BATTERY and self.energy_mwh is None:
            raise ValueError("battery resources require energy_mwh")


@dataclass(frozen=True)
class FlexibilityPortfolio(DomainContract):
    portfolio_id: str
    resources: tuple[FlexibilityResource, ...]
    schema_version: str = RESOURCE_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != RESOURCE_SCHEMA_VERSION:
            raise ValueError("unsupported flexibility-portfolio schema")
        require_non_empty(self.portfolio_id, "portfolio_id")
        identifiers = []
        for resource in self.resources:
            resource.validate()
            identifiers.append(resource.resource_id)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("resource identifiers must be unique")
