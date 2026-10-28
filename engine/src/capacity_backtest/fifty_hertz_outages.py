"""Normalize the official rolling 50Hertz transmission-outage revision feed."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .events import GeographicResolution, GridEvent
from .storage import SnapshotStore, atomic_write

SOURCE_ID = "fifty_hertz_outages_rss"
URL = (
    "https://www.50hertz.com/Transparency/GridData/Congestionmanagement/"
    "OutageandPlanning?view=rss&SplitView=false"
)
GUID = re.compile(r"/Id/(\d+)/Version/(\d+)")


def _rows(description: str) -> dict[str, str]:
    decoded = html.unescape(description)
    result = {}
    for key, value in re.findall(
        r"<tr>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*</tr>",
        decoded,
        re.DOTALL | re.IGNORECASE,
    ):
        clean_key = re.sub(r"<[^>]+>", "", html.unescape(key)).strip().rstrip(":")
        clean_value = re.sub(r"<[^>]+>", "", html.unescape(value)).strip()
        result[clean_key] = clean_value
    return result


def parse_outage_rss(
    content: bytes, *, retrieved_at: datetime, snapshot_hash: str
) -> list[GridEvent]:
    root = ET.fromstring(content)
    events = []
    for item in root.findall("./channel/item"):
        guid = (item.findtext("guid") or "").strip()
        match = GUID.search(guid)
        if not match:
            raise ValueError(f"invalid outage GUID: {guid}")
        fields = _rows(item.findtext("description") or "")
        start_raw = fields.get("Beginn")
        end_raw = fields.get("Ende") or fields.get("Voraussichtliches Ende")
        published_raw = item.findtext("pubDate")
        if not start_raw or not end_raw or not published_raw:
            raise ValueError(f"outage {guid} lacks required timestamps")
        starts_at = datetime.strptime(start_raw, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        ends_at = datetime.strptime(end_raw, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        published_at = datetime.strptime(published_raw, "%a, %d %b %Y %H:%M:%S %z")
        external_id = fields.get("Revisionsplanungs-ID") or fields.get("Störungs-ID") or ""
        external_revision = re.search(r"_(\d+)$", external_id)
        title = item.findtext("title") or ""
        kind = (
            "planned_transmission_outage"
            if "Revision" in title
            else "unplanned_transmission_outage"
        )
        asset = fields.get("Netzelement")
        event = GridEvent(
            event_id=f"50hertz-outage-{match.group(1)}",
            published_at=published_at,
            starts_at=starts_at,
            ends_at=ends_at,
            operator="50Hertz Transmission GmbH",
            area=fields.get("Marktgebiet") or "50Hertz control area",
            kind=kind,
            direction=None,
            power_mw=None,
            energy_mwh=None,
            revision=int(external_revision.group(1)) if external_revision else int(match.group(2)),
            source_id=SOURCE_ID,
            source_record_id=guid,
            retrieved_at=retrieved_at,
            bidding_zone="DE-LU",
            control_area="10YDE-VE-------2",
            affected_asset_ids=(asset,) if asset else (),
            affected_geography=fields.get("Marktgebiet"),
            reason=fields.get("Grund"),
            status="published",
            geographic_resolution=(
                GeographicResolution.ASSET if asset else GeographicResolution.CONTROL_AREA
            ),
            asset_match_confidence=1.0 if asset else None,
            source_url=guid,
            snapshot_hash=snapshot_hash,
            validation_warnings=(
                "Affected-capacity percentage is not converted to MW.",
                "RSS is rolling and does not establish a complete historical outage archive.",
            ),
        )
        event.validate()
        events.append(event)
    return events


def capture_outage_rss(data_root: Path) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        response = client.get(URL, headers={"User-Agent": "GridPulseCapacityBacktest/0.2"})
        response.raise_for_status()
    stored = SnapshotStore(data_root).capture(
        source_id=SOURCE_ID,
        publisher="50Hertz Transmission GmbH",
        source_url=URL,
        content=response.content,
        extension="xml",
        retrieved_at=retrieved_at,
        request={"view": "rss", "split_view": False},
        response_headers={
            key: value
            for key, value in response.headers.items()
            if key.lower() in {"content-type", "content-length", "etag", "last-modified"}
        },
        truth_class="operator_published",
        geographic_resolution="transmission_asset",
        licence="unconfirmed",
        adapter_version="fifty-hertz-outages-v1",
        limitations=(
            "Rolling feed is not a complete historical publication archive.",
            "Outages do not establish equipment ratings, loading or available MW.",
        ),
    )
    events = parse_outage_rss(
        response.content, retrieved_at=retrieved_at, snapshot_hash=stored.sha256
    )
    normalized = data_root / "normalized" / "grid-events-v1" / SOURCE_ID / f"{stored.sha256}.jsonl"
    atomic_write(
        normalized,
        ("\n".join(_json(event.as_dict()) for event in events) + "\n").encode(),
    )
    revisions: dict[str, int] = {}
    for event in events:
        revisions[event.event_id] = max(revisions.get(event.event_id, 0), event.revision)
    quality = {
        "schema_version": "fifty-hertz-outage-quality-v1",
        "source_id": SOURCE_ID,
        "snapshot_hash": stored.sha256,
        "records": len(events),
        "unique_events": len(revisions),
        "revised_events": sum(value > 1 for value in revisions.values()),
        "asset_records": sum(bool(event.affected_asset_ids) for event in events),
        "unknown_power_records": sum(event.power_mw is None for event in events),
        "publication_time_validated": True,
        "revision_history_complete": False,
        "training_admitted": False,
    }
    quality_path = data_root / "quality" / SOURCE_ID / f"{stored.sha256}.json"
    atomic_write(quality_path, (_json(quality) + "\n").encode())
    return {
        "records": len(events),
        "manifest": str(stored.manifest_path),
        "normalized": str(normalized),
        "quality": str(quality_path),
        "profile": quality,
    }


def _json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)
