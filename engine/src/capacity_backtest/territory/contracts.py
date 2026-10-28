"""Immutable contracts for location, territory, operator, and confirmation evidence."""

from __future__ import annotations

from dataclasses import dataclass

from capacity_backtest.domain.base import DomainContract, parse_aware_timestamp, require_non_empty

LOCATION_METHODS = {
    "operator_provided", "cadastral_parcel", "address_rooftop", "address_interpolated",
    "customer_coordinates", "postcode_centroid", "manual_review",
}
MATCH_STATUSES = {
    "matched", "boundary", "overlapping", "uncovered", "ambiguous",
    "insufficient_geometry", "historically_unavailable",
}
RESPONSIBILITY_STATUSES = {
    "candidate", "validated_geographic_match", "requires_operator_study",
    "operator_confirmed", "ambiguous", "unresolved",
}
CONFIRMATION_SCOPES = {
    "territory_only", "connection_enquiry_received", "responsible_operator",
    "candidate_pcc_assigned", "connection_study_outcome", "contractual_connection",
}


@dataclass(frozen=True)
class SiteLocation(DomainContract):
    site_id: str
    latitude: float
    longitude: float
    coordinate_method: str
    coordinate_source_id: str
    observed_at: str
    address: str | None = None
    parcel_geometry: dict[str, object] | None = None
    coordinate_accuracy_m: float | None = None
    schema_version: str = "gridpulse-site-location-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-site-location-v1":
            raise ValueError("unsupported site-location schema")
        require_non_empty(self.site_id, "site_id")
        require_non_empty(self.coordinate_source_id, "coordinate_source_id")
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ValueError("invalid site coordinates")
        if self.coordinate_method not in LOCATION_METHODS:
            raise ValueError("unsupported coordinate method")
        if self.coordinate_accuracy_m is not None and self.coordinate_accuracy_m < 0:
            raise ValueError("coordinate accuracy must be non-negative")
        parse_aware_timestamp(self.observed_at, "observed_at")
        if self.parcel_geometry is not None and self.parcel_geometry.get("type") not in {
            "Polygon", "MultiPolygon",
        }:
            raise ValueError("parcel geometry must be Polygon or MultiPolygon GeoJSON")


@dataclass(frozen=True)
class TerritorySnapshot(DomainContract):
    territory_id: str
    operator_id: str
    operator_name: str
    network_level: str
    geometry: dict[str, object]
    valid_from: str
    valid_to: str | None
    published_at: str
    retrieved_at: str
    source_id: str
    source_url: str
    artifact_hash: str
    licence: str
    evidence_class: str
    schema_version: str = "gridpulse-territory-snapshot-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-territory-snapshot-v1":
            raise ValueError("unsupported territory-snapshot schema")
        for value, name in ((self.territory_id, "territory_id"), (self.operator_id, "operator_id"),
                            (self.operator_name, "operator_name"), (self.source_id, "source_id"),
                            (self.licence, "licence"), (self.evidence_class, "evidence_class")):
            require_non_empty(value, name)
        if self.network_level not in {"distribution", "transmission", "closed_distribution"}:
            raise ValueError("unsupported network level")
        if self.geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("territory geometry must be Polygon or MultiPolygon GeoJSON")
        valid_from = parse_aware_timestamp(self.valid_from, "valid_from")
        valid_to = parse_aware_timestamp(self.valid_to, "valid_to") if self.valid_to else None
        published = parse_aware_timestamp(self.published_at, "published_at")
        parse_aware_timestamp(self.retrieved_at, "retrieved_at")
        if valid_to is not None and valid_to <= valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if published > parse_aware_timestamp(self.retrieved_at, "retrieved_at"):
            raise ValueError("published_at cannot be later than retrieved_at")
        if len(self.artifact_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in self.artifact_hash):
            raise ValueError("artifact_hash must be SHA-256")
        if not self.source_url.startswith("https://"):
            raise ValueError("territory source URL must use HTTPS")


@dataclass(frozen=True)
class TerritoryMatch(DomainContract):
    site_id: str
    territory_id: str | None
    operator_id: str | None
    match_status: str
    match_method: str
    confidence: float
    distance_to_boundary_m: float | None
    competing_operator_ids: tuple[str, ...] = ()
    review_required: bool = True
    evidence_ids: tuple[str, ...] = ()
    schema_version: str = "gridpulse-territory-match-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-territory-match-v1":
            raise ValueError("unsupported territory-match schema")
        require_non_empty(self.site_id, "site_id")
        require_non_empty(self.match_method, "match_method")
        if self.match_status not in MATCH_STATUSES or not 0 <= self.confidence <= 1:
            raise ValueError("invalid territory match")
        if self.distance_to_boundary_m is not None and self.distance_to_boundary_m < 0:
            raise ValueError("boundary distance must be non-negative")
        if self.match_status == "matched" and (not self.territory_id or not self.operator_id):
            raise ValueError("matched territory requires territory and operator identity")


@dataclass(frozen=True)
class OperatorRegistryEntry(DomainContract):
    operator_id: str
    legal_name: str
    market_roles: tuple[str, ...]
    status: str
    source_id: str
    artifact_hash: str
    mastr_number: str | None = None
    bdew_code: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    aliases: tuple[str, ...] = ()
    schema_version: str = "gridpulse-operator-registry-entry-v1"

    def validate(self) -> None:
        for value, name in ((self.operator_id, "operator_id"), (self.legal_name, "legal_name"),
                            (self.status, "status"), (self.source_id, "source_id")):
            require_non_empty(value, name)
        if not self.market_roles or "stromnetzbetreiber" not in {r.lower() for r in self.market_roles}:
            raise ValueError("operator registry entry requires Stromnetzbetreiber role")
        if len(self.artifact_hash) != 64:
            raise ValueError("artifact_hash must be SHA-256")
        start = parse_aware_timestamp(self.valid_from, "valid_from") if self.valid_from else None
        end = parse_aware_timestamp(self.valid_to, "valid_to") if self.valid_to else None
        if start and end and end <= start:
            raise ValueError("operator validity interval is invalid")


@dataclass(frozen=True)
class ResponsibilityResult(DomainContract):
    site_id: str
    geographic_dso_id: str | None
    candidate_connection_operator_id: str | None
    candidate_connection_level: str
    status: str
    exception_flags: tuple[str, ...]
    review_required: bool
    evidence_ids: tuple[str, ...]
    schema_version: str = "gridpulse-responsibility-result-v1"

    def validate(self) -> None:
        require_non_empty(self.site_id, "site_id")
        if self.status not in RESPONSIBILITY_STATUSES:
            raise ValueError("invalid responsibility status")
        if self.candidate_connection_level not in {"distribution", "transmission", "unknown"}:
            raise ValueError("invalid candidate connection level")


@dataclass(frozen=True)
class OperatorResponsibilityConfirmation(DomainContract):
    confirmation_id: str
    site_id: str
    operator_id: str
    operator_registry_id: str
    confirmation_scope: str
    valid_from: str
    issued_at: str
    source_document_hash: str
    source_locator: str
    signatory_or_channel: str
    review_status: str
    candidate_pcc_id: str | None = None
    voltage_kv: float | None = None
    valid_to: str | None = None
    schema_version: str = "gridpulse-operator-responsibility-confirmation-v1"

    def validate(self) -> None:
        for value, name in ((self.confirmation_id, "confirmation_id"), (self.site_id, "site_id"),
                            (self.operator_id, "operator_id"), (self.operator_registry_id, "operator_registry_id"),
                            (self.source_locator, "source_locator"), (self.signatory_or_channel, "signatory_or_channel")):
            require_non_empty(value, name)
        if self.confirmation_scope not in CONFIRMATION_SCOPES:
            raise ValueError("invalid confirmation scope")
        start = parse_aware_timestamp(self.valid_from, "valid_from")
        end = parse_aware_timestamp(self.valid_to, "valid_to") if self.valid_to else None
        parse_aware_timestamp(self.issued_at, "issued_at")
        if end and end <= start:
            raise ValueError("confirmation validity interval is invalid")
        if len(self.source_document_hash) != 64:
            raise ValueError("source_document_hash must be SHA-256")
        if self.review_status != "reviewed":
            raise ValueError("operator confirmation must be reviewed")
        if self.confirmation_scope in {"candidate_pcc_assigned", "connection_study_outcome", "contractual_connection"} and not self.candidate_pcc_id:
            raise ValueError("PCC-scoped confirmation requires candidate_pcc_id")
        if self.voltage_kv is not None and self.voltage_kv <= 0:
            raise ValueError("voltage_kv must be positive")
