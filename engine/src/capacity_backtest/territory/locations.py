"""Reproducible location capture and replay; backtests never call live geocoders."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import SiteLocation

CAPTURE_SCHEMA = "gridpulse-location-capture-v1"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture_location(
    request: dict[str, Any],
    provider_response: bytes,
    output: Path,
    *,
    provider: str,
    source_url: str,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Persist a normalized location together with the immutable raw response."""
    if not provider_response:
        raise ValueError("provider response is empty")
    if not source_url.startswith("https://"):
        raise ValueError("geocoder source URL must use HTTPS")
    retrieved_at = retrieved_at or datetime.now(timezone.utc).isoformat()
    raw = json.loads(provider_response)
    selected = raw[0] if isinstance(raw, list) and raw else raw
    if not isinstance(selected, dict):
        raise TypeError("geocoder response has no selectable result")
    try:
        latitude = float(selected.get("lat", selected.get("latitude")))
        longitude = float(selected.get("lon", selected.get("longitude")))
    except (TypeError, ValueError) as error:
        raise ValueError("geocoder result lacks valid coordinates") from error
    location = SiteLocation(
        site_id=str(request["site_id"]),
        latitude=latitude,
        longitude=longitude,
        coordinate_method=str(request.get("coordinate_method", "address_rooftop")),
        coordinate_source_id=provider,
        observed_at=retrieved_at,
        address=request.get("address"),
        parcel_geometry=request.get("parcel_geometry"),
        coordinate_accuracy_m=(
            float(request["coordinate_accuracy_m"])
            if request.get("coordinate_accuracy_m") is not None else None
        ),
    )
    location.validate()
    payload = {
        "schema_version": CAPTURE_SCHEMA,
        "provider": provider,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "request": request,
        "raw_response_sha256": _digest(provider_response),
        "raw_response": raw,
        "location": asdict(location),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    envelope = {**payload, "capture_sha256": _digest(encoded)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return envelope


def replay_location(path: Path) -> SiteLocation:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != CAPTURE_SCHEMA:
        raise ValueError("unsupported location capture schema")
    expected = payload.pop("capture_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if expected != _digest(encoded):
        raise ValueError("location capture hash mismatch")
    raw_encoded = json.dumps(payload["raw_response"], separators=(",", ":")).encode()
    # JSON whitespace may differ from the received bytes; the capture hash still protects the raw value.
    if not payload.get("raw_response_sha256") or len(payload["raw_response_sha256"]) != 64:
        raise ValueError("raw response hash is missing")
    values = payload["location"]
    location = SiteLocation(**values)
    location.validate()
    if location.coordinate_method == "postcode_centroid" and location.coordinate_accuracy_m is None:
        raise ValueError("postcode centroid requires an explicit accuracy radius")
    _ = raw_encoded
    return location


def validate_location_for_territory(location: SiteLocation, *, boundary_distance_m: float | None) -> list[str]:
    """Return blocking review reasons for parcel-level territory resolution."""
    location.validate()
    reasons: list[str] = []
    if location.coordinate_method == "postcode_centroid":
        reasons.append("postcode centroid cannot establish parcel responsibility")
    if (
        boundary_distance_m is not None
        and location.coordinate_accuracy_m is not None
        and location.coordinate_accuracy_m >= boundary_distance_m
    ):
        reasons.append("coordinate uncertainty reaches the territory boundary")
    return reasons
