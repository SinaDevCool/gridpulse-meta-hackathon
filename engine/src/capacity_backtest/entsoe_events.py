"""Bounded ENTSO-E event probes with explicit revision-retention findings."""

from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from .events import GeographicResolution, GridEvent
from .storage import SnapshotStore, atomic_write

API_URL = "https://web-api.tp.entsoe.eu/api"
DE_LU = "10Y1001A1001A82H"
SOURCE_ID = "entsoe_a78_transmission_outages"


def _text(element: ET.Element, suffix: str) -> str | None:
    item = next((node for node in element.iter() if node.tag.endswith(suffix)), None)
    return item.text if item is not None else None


def _timestamp(value: str | None) -> datetime:
    if not value:
        raise ValueError("ENTSO-E event timestamp is missing")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_a78_zip(content: bytes, *, retrieved_at: datetime, snapshot_hash: str) -> list[GridEvent]:
    events = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".xml"):
                raise ValueError(f"unexpected ENTSO-E archive member: {name}")
            root = ET.fromstring(archive.read(name))
            document_id = _text(root, "mRID")
            revision = _text(root, "revisionNumber")
            created = _text(root, "createdDateTime")
            start = _text(root, "unavailability_Time_Period.timeInterval/start")
            end = _text(root, "unavailability_Time_Period.timeInterval/end")
            # ElementTree suffix matching cannot express a path reliably across namespace versions.
            interval = next(
                (
                    node
                    for node in root.iter()
                    if node.tag.endswith("unavailability_Time_Period.timeInterval")
                ),
                None,
            )
            if interval is not None:
                start = _text(interval, "start")
                end = _text(interval, "end")
            series = next((node for node in root.iter() if node.tag.endswith("TimeSeries")), None)
            asset = (
                next(
                    (node for node in root.iter() if node.tag.endswith("Asset_RegisteredResource")),
                    None,
                )
                if series is not None
                else None
            )
            asset_id = _text(asset, "mRID") if asset is not None else None
            asset_name = _text(asset, "name") if asset is not None else None
            business_type = _text(series, "businessType") if series is not None else None
            event = GridEvent(
                event_id=str(document_id),
                published_at=_timestamp(created),
                starts_at=_timestamp(start),
                ends_at=_timestamp(end),
                operator="ENTSO-E Transparency Platform / reporting TSO",
                area="Germany-Luxembourg bidding-zone outage query",
                kind=(
                    "planned_transmission_outage"
                    if business_type == "A53"
                    else "unplanned_transmission_outage"
                    if business_type == "A54"
                    else "transmission_unavailability"
                ),
                direction=None,
                power_mw=None,
                energy_mwh=None,
                revision=int(revision or 0),
                source_id=SOURCE_ID,
                source_record_id=f"{document_id}:{revision}",
                retrieved_at=retrieved_at,
                bidding_zone="DE-LU",
                affected_asset_ids=(asset_id,) if asset_id else (),
                affected_geography=_text(asset, "location.name") if asset is not None else None,
                reason=_text(series, "Reason/text") if series is not None else None,
                status=_text(root, "docStatus/value") or "effective_latest_returned",
                geographic_resolution=(
                    GeographicResolution.ASSET if asset_id else GeographicResolution.BIDDING_ZONE
                ),
                asset_match_confidence=1.0 if asset_id else None,
                source_url=API_URL,
                snapshot_hash=snapshot_hash,
                validation_warnings=(
                    f"Published asset name: {asset_name}"
                    if asset_name
                    else "Asset name unavailable",
                    "Ordinary REST extraction returned the effective/latest revision only.",
                    "No equipment rating or available MW is inferred.",
                ),
            )
            event.validate()
            events.append(event)
    return events


def _token() -> str:
    token = os.environ.get("ENTSOE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("ENTSOE_TOKEN is not configured")
    return token


def capture_a78_probe(start: datetime, end: datetime, data_root: Path) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    common = {
        "documentType": "A78",
        "biddingZone_Domain": DE_LU,
        "periodStart": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
        "periodEnd": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
    }
    events = []
    manifests = []
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for offset in range(0, 10_000, 200):
            params = {**common, "offset": offset, "securityToken": _token()}
            response = client.get(API_URL, params=params)
            response.raise_for_status()
            safe_request = {key: value for key, value in params.items() if key != "securityToken"}
            stored = SnapshotStore(data_root).capture(
                source_id=SOURCE_ID,
                publisher="ENTSO-E Transparency Platform",
                source_url=API_URL,
                content=response.content,
                extension="zip",
                retrieved_at=datetime.now(timezone.utc),
                request=safe_request,
                response_headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() in {"content-type", "content-length", "etag", "last-modified"}
                },
                truth_class="operator_published",
                geographic_resolution="transmission_asset_or_bidding_zone",
                licence="ENTSO-E Transparency Platform terms",
                adapter_version="entsoe-events-v1",
                limitations=(
                    "REST extraction returns effective documents and does not prove retention of superseded revisions.",
                    "Transmission outages do not establish distribution-node available capacity.",
                ),
            )
            page = parse_a78_zip(
                response.content, retrieved_at=retrieved_at, snapshot_hash=stored.sha256
            )
            events.extend(page)
            manifests.append(str(stored.manifest_path))
            if len(page) < 200:
                break
        else:
            raise RuntimeError("ENTSO-E A78 pagination exceeded safety bound")
    normalized = data_root / "normalized" / "grid-events-v1" / SOURCE_ID
    output = normalized / f"{common['periodStart']}_{common['periodEnd']}.jsonl"
    atomic_write(output, ("\n".join(_json(item.as_dict()) for item in events) + "\n").encode())
    quality = {
        "schema_version": "entsoe-event-probe-v1",
        "source_id": SOURCE_ID,
        "period_start": start.astimezone(timezone.utc).isoformat(),
        "period_end": end.astimezone(timezone.utc).isoformat(),
        "records": len(events),
        "unique_document_ids": len({event.event_id for event in events}),
        "maximum_revision": max((event.revision for event in events), default=None),
        "pages": len(manifests),
        "historical_revision_parameter_supported": False,
        "revision_history_complete": False,
        "training_admitted": False,
        "finding": "A78 supports offset pagination, but revisionNumber is rejected as an input parameter and mRID retrieval returns the latest document.",
    }
    quality_path = (
        data_root / "quality" / SOURCE_ID / f"{common['periodStart']}_{common['periodEnd']}.json"
    )
    atomic_write(quality_path, (_json(quality) + "\n").encode())
    return {
        "manifests": manifests,
        "normalized": str(output),
        "quality": str(quality_path),
        "profile": quality,
    }


def capture_a63_probe(start: datetime, end: datetime, data_root: Path) -> dict[str, Any]:
    params = {
        "documentType": "A63",
        "biddingZone_Domain": DE_LU,
        "periodStart": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
        "periodEnd": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
        "securityToken": _token(),
    }
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        response = client.get(API_URL, params=params)
    safe_request = {key: value for key, value in params.items() if key != "securityToken"}
    stored = SnapshotStore(data_root).capture(
        source_id="entsoe_a63_redispatch_probe",
        publisher="ENTSO-E Transparency Platform",
        source_url=API_URL,
        content=response.content,
        extension="xml",
        retrieved_at=datetime.now(timezone.utc),
        request=safe_request,
        status="unsupported_by_rest_api" if response.status_code == 400 else "unexpected_response",
        truth_class="operator_published",
        geographic_resolution="bidding_zone",
        licence="ENTSO-E Transparency Platform terms",
        adapter_version="entsoe-events-v1",
        limitations=("A63 is not available through this REST extraction combination.",),
    )
    reason = _text(ET.fromstring(response.content), "text")
    result = {
        "schema_version": "entsoe-a63-probe-v1",
        "http_status": response.status_code,
        "reason": reason,
        "manifest": str(stored.manifest_path),
        "training_admitted": False,
    }
    quality = data_root / "quality" / "entsoe_a63_redispatch_probe" / f"{stored.sha256}.json"
    atomic_write(quality, (_json(result) + "\n").encode())
    return {**result, "quality": str(quality)}


def _json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)
