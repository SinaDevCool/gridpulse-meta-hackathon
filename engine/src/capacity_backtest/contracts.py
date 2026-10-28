"""Evidence contracts and fail-closed truth classifications."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TruthClass(str, Enum):
    OPERATOR_CONFIRMED = "operator_confirmed"
    OPERATOR_RECONCILED = "operator_reconciled"
    OPERATOR_MODEL_UNVALIDATED = "operator_model_unvalidated"
    OPERATOR_PUBLISHED = "operator_published"
    CALCULATED_VALIDATED = "calculated_validated"
    EXPERIMENTAL_ESTIMATE = "experimental_estimate"
    CONSTRAINT_DETECTED = "constraint_detected"
    PLANNED_REINFORCEMENT = "planned_reinforcement"
    SYNTHETIC_DEMONSTRATION = "synthetic_demonstration"
    SYNTHETIC_BENCHMARK = "synthetic_benchmark"
    PUBLIC_SCREENING = "public_screening"
    UNKNOWN = "unknown"


class SufficiencyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    CONDITIONAL = "conditionally_sufficient"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    publisher: str
    title: str
    url: str
    format: str
    authority: str
    coverage: str
    voltage_scope: list[float]
    purposes: list[str]
    prohibited_uses: list[str]
    truth_class: TruthClass
    enabled: bool = True
    disabled_reason: str | None = None

    def validate(self) -> None:
        if not self.id or not self.publisher or not self.title:
            raise ValueError("source id, publisher and title are required")
        if not self.url.startswith("https://"):
            raise ValueError(f"source {self.id} must use an HTTPS authoritative URL")
        if not self.purposes or not self.prohibited_uses:
            raise ValueError(f"source {self.id} requires purposes and prohibited uses")
        if not self.enabled and not self.disabled_reason:
            raise ValueError(f"disabled source {self.id} requires a reason")


@dataclass(frozen=True)
class ArtifactManifest:
    source_id: str
    source_url: str
    retrieved_at: str
    sha256: str
    byte_length: int
    content_type: str
    original_filename: str
    http_status: int
    truth_class: TruthClass
    limitations: list[str] = field(default_factory=list)
    publication_date: str | None = None
    reporting_period: str | None = None
    request_method: str = "GET"
    response_headers: dict[str, str] = field(default_factory=dict)
    schema_fingerprint: str | None = None
    adapter_version: str | None = None
    storage_path: str | None = None
    licence: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["truth_class"] = self.truth_class.value
        return value


@dataclass(frozen=True)
class NormalizedRecord:
    source_id: str
    source_version: str
    source_sha256: str
    retrieved_at: str
    source_locator: str
    transformation_version: str
    truth_class: TruthClass
    limitations: list[str]
    values: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["truth_class"] = self.truth_class.value
        return value


CAPACITY_TRUTH_CLASSES = {
    TruthClass.OPERATOR_CONFIRMED,
}

TRUTH_CLASS_ALIASES = {
    "synthetic_benchmark_truth": TruthClass.SYNTHETIC_BENCHMARK,
    "synthetic_scenario": TruthClass.SYNTHETIC_DEMONSTRATION,
}


def coerce_truth_class(value: TruthClass | str) -> TruthClass:
    """Return the canonical truth class, accepting only documented legacy aliases."""

    if isinstance(value, TruthClass):
        return value
    normalized = str(value).strip().lower()
    if normalized in TRUTH_CLASS_ALIASES:
        return TRUTH_CLASS_ALIASES[normalized]
    try:
        return TruthClass(normalized)
    except ValueError as error:
        raise ValueError(f"unknown truth class: {value!r}") from error


def assert_capacity_claim_allowed(truth_class: TruthClass | str, value_mw: float | None) -> None:
    """Reject available-capacity claims from screening or synthetic evidence."""

    canonical = coerce_truth_class(truth_class)
    if value_mw is not None and canonical not in CAPACITY_TRUTH_CLASSES:
        raise ValueError(
            f"{canonical.value} evidence cannot establish available connection capacity"
        )
