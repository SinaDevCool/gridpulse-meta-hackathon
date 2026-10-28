"""Immutable capture and profiling primitives for regional public grid sources."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import httpx

from .storage import SnapshotStore, atomic_write

ADAPTER_VERSION = "regional-ingest-v2"


class CaptureStatus(str, Enum):
    SUCCESS_WITH_RECORDS = "success_with_records"
    SUCCESS_EMPTY = "success_empty"
    SOURCE_UNAVAILABLE = "source_unavailable"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    SCHEMA_CHANGED = "schema_changed"
    INVALID_CONTENT = "invalid_content"
    PARTIAL_DOWNLOAD = "partial_download"


@dataclass(frozen=True)
class EndpointDefinition:
    source_id: str
    publisher: str
    url: str
    format: str
    geographic_resolution: str
    truth_class: str = "operator_published"
    licence: str = "unconfirmed"
    expected_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptureResult:
    status: CaptureStatus
    artifact_path: Path | None
    manifest_path: Path | None
    byte_length: int
    sha256: str | None
    error: str | None = None


def schema_fingerprint(records: list[dict[str, Any]]) -> str:
    fields = sorted({key for record in records for key in record})
    types = {key: sorted({type(record.get(key)).__name__ for record in records}) for key in fields}
    canonical = json.dumps({"fields": fields, "types": types}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def parse_edis_rss(content: bytes) -> list[dict[str, str | None]]:
    """Parse the public completed-measures feed without inventing publication semantics."""
    root = ET.fromstring(content)
    records = []
    for item in root.findall("./channel/item"):
        description = item.findtext("description") or ""
        fields: dict[str, str] = {}
        for line in description.replace("<br />", "\n").replace("<br/>", "\n").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        records.append(
            {
                "guid": item.findtext("guid"),
                "title": item.findtext("title"),
                "rss_pub_date_raw": item.findtext("pubDate"),
                "description_raw": description,
                "operation_id": fields.get("Einsatz-ID"),
                "area": fields.get("Gebiet"),
                "constraint_location": fields.get("Ort Engpass"),
                "installation_key": fields.get("Anlagenschlüssel"),
            }
        )
    return records


def parse_generic_rss(content: bytes) -> list[dict[str, str | None]]:
    """Preserve generic RSS fields without assuming pubDate semantics."""
    root = ET.fromstring(content)
    return [
        {
            "guid": item.findtext("guid"),
            "title": item.findtext("title"),
            "pub_date_raw": item.findtext("pubDate"),
            "description_raw": item.findtext("description"),
            "link": item.findtext("link"),
        }
        for item in root.findall("./channel/item")
    ]


def parse_delimited(content: bytes, *, delimiter: str = ";") -> list[dict[str, str]]:
    text = content.decode("utf-8-sig")
    return [dict(row) for row in csv.DictReader(StringIO(text), delimiter=delimiter)]


def profile_records(
    endpoint: EndpointDefinition, records: list[dict[str, Any]], *, snapshot_hash: str
) -> dict[str, Any]:
    fields = sorted({key for record in records for key in record})
    missing_required = sorted(set(endpoint.expected_fields) - set(fields))
    nulls = {field: sum(record.get(field) in (None, "") for record in records) for field in fields}
    duplicate_rows = len(records) - len({json.dumps(record, sort_keys=True) for record in records})
    return {
        "schema_version": "regional-source-quality-v1",
        "source_id": endpoint.source_id,
        "snapshot_hash": snapshot_hash,
        "record_count": len(records),
        "fields": fields,
        "missing_required_fields": missing_required,
        "null_counts": nulls,
        "duplicate_rows": duplicate_rows,
        "schema_fingerprint": schema_fingerprint(records),
        "geographic_resolution": endpoint.geographic_resolution,
        "publication_time_validated": False,
        "revision_history_complete": False,
        "zero_semantics_validated": False,
        "units_validated": False,
        "training_admitted": False,
        "warnings": [
            "Publication-time semantics require source-specific validation.",
            "Absence of records must not be interpreted as zero events.",
        ],
    }


def profile_artifact(
    endpoint: EndpointDefinition, content: bytes, *, snapshot_hash: str
) -> dict[str, Any]:
    """Quality profile non-tabular publications without pretending they contain records."""
    lowered = content[:4096].lower()
    signatures = {
        "html": b"<html" in lowered or b"<!doctype html" in lowered,
        "pdf": content.startswith(b"%PDF"),
        "xml": lowered.lstrip().startswith(b"<?xml") or b"<rss" in lowered,
        "csv": bool(content.strip()),
        "xlsx": content.startswith(b"PK"),
        "zip": content.startswith(b"PK"),
    }
    valid = signatures.get(endpoint.format, bool(content))
    return {
        "schema_version": "regional-artifact-quality-v1",
        "source_id": endpoint.source_id,
        "snapshot_hash": snapshot_hash,
        "byte_length": len(content),
        "format": endpoint.format,
        "format_signature_valid": valid,
        "geographic_resolution": endpoint.geographic_resolution,
        "publication_time_validated": False,
        "revision_history_complete": False,
        "zero_semantics_validated": False,
        "units_validated": False,
        "training_admitted": False,
        "warnings": [
            "This publication supplies context or discovery metadata, not a zero-event series.",
            "No nodal loading, headroom, or available connection MW may be inferred.",
        ],
    }


def profile_netztransparenz_archive(content: bytes, *, snapshot_hash: str) -> dict[str, Any]:
    """Profile the official archive without treating it as a revision-complete publication log."""
    with zipfile.ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].lower().endswith(".csv"):
            raise ValueError("expected exactly one CSV in redispatch archive")
        raw = archive.read(names[0])
    text = raw.decode("utf-8-sig")
    records = [dict(row) for row in csv.DictReader(StringIO(text), delimiter=";")]
    fields = list(records[0]) if records else []
    required = {
        "BEGINN_DATUM",
        "BEGINN_UHRZEIT",
        "ZEITZONE_VON",
        "ENDE_DATUM",
        "ENDE_UHRZEIT",
        "ZEITZONE_BIS",
        "RICHTUNG",
        "MITTLERE_LEISTUNG_MW",
        "MAXIMALE_LEISTUNG_MW",
        "GESAMTE_ARBEIT_MWH",
        "ANWEISENDER_UENB",
        "ANFORDERNDER_UENB",
        "BETROFFENE_ANLAGE",
    }
    dates = [record["BEGINN_DATUM"] for record in records if record.get("BEGINN_DATUM")]
    parsed_dates = [
        datetime.strptime(value, "%d.%m.%Y").replace(tzinfo=timezone.utc).date() for value in dates
    ]
    numeric_fields = ("MITTLERE_LEISTUNG_MW", "MAXIMALE_LEISTUNG_MW", "GESAMTE_ARBEIT_MWH")
    invalid_numeric = {
        field: sum(not _german_number(record.get(field)) for record in records)
        for field in numeric_fields
    }
    key_fields = [field for field in fields if field not in numeric_fields]
    duplicate_records = len(records) - len(
        {tuple(record.get(field) for field in fields) for record in records}
    )
    return {
        "schema_version": "regional-source-quality-v1",
        "source_id": "netztransparenz_redispatch_archive_2013_2020",
        "snapshot_hash": snapshot_hash,
        "archive_members": names,
        "record_count": len(records),
        "fields": fields,
        "missing_required_fields": sorted(required - set(fields)),
        "coverage_start": min(parsed_dates).isoformat() if parsed_dates else None,
        "coverage_end": max(parsed_dates).isoformat() if parsed_dates else None,
        "timezone_values": sorted(
            {
                record.get(field, "")
                for record in records
                for field in ("ZEITZONE_VON", "ZEITZONE_BIS")
            }
        ),
        "invalid_numeric_counts": invalid_numeric,
        "duplicate_records": duplicate_records,
        "identity_key_fields": key_fields,
        "publication_time_validated": False,
        "revision_history_complete": False,
        "stable_source_record_id": False,
        "empty_distinguishable_from_failure": False,
        "units_validated": all(value == 0 for value in invalid_numeric.values()),
        "training_admitted": False,
        "warnings": [
            "Archive contains event outcomes but no publication timestamp or revision number.",
            "The archive lacks the NETZREGION column described for the current API format.",
            "Coverage regime changes after 2020 require separate source-period handling.",
            "Affected installation is not assumed to be a distribution substation.",
        ],
    }


def _german_number(value: str | None) -> bool:
    if value in (None, ""):
        return False
    try:
        float(value.replace(".", "").replace(",", "."))
        return True
    except ValueError:
        return False


def _status_for_http(status: int) -> CaptureStatus:
    if status in (401, 403):
        return CaptureStatus.AUTHENTICATION_FAILED
    if status == 429:
        return CaptureStatus.RATE_LIMITED
    return CaptureStatus.SOURCE_UNAVAILABLE


def capture_endpoint(
    endpoint: EndpointDefinition,
    data_root: Path,
    work_root: Path,
    *,
    client: httpx.Client | None = None,
    retrieved_at: datetime | None = None,
) -> CaptureResult:
    """Capture through local staging, then hash-verify an immutable OneDrive copy."""
    own_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=60.0)
    timestamp = retrieved_at or datetime.now(timezone.utc)
    staging = work_root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    descriptor = None
    temporary_name = None
    try:
        response = http.get(endpoint.url, headers={"User-Agent": "GridPulseCapacityBacktest/0.2"})
        if response.status_code >= 400:
            return CaptureResult(_status_for_http(response.status_code), None, None, 0, None)
        descriptor, temporary_name = tempfile.mkstemp(dir=staging, suffix=f".{endpoint.format}")
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(response.content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary = Path(temporary_name)
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() in {"content-type", "content-length", "etag", "last-modified"}
        }
        stored = SnapshotStore(data_root).capture(
            source_id=endpoint.source_id,
            publisher=endpoint.publisher,
            source_url=endpoint.url,
            content=temporary.read_bytes(),
            extension=endpoint.format,
            retrieved_at=timestamp,
            request={"method": "GET"},
            response_headers=headers,
            status=(
                CaptureStatus.SUCCESS_WITH_RECORDS.value
                if response.content
                else CaptureStatus.SUCCESS_EMPTY.value
            ),
            truth_class=endpoint.truth_class,
            geographic_resolution=endpoint.geographic_resolution,
            licence=endpoint.licence,
            adapter_version=ADAPTER_VERSION,
            limitations=(
                "Does not establish nodal loading, headroom, or available connection MW.",
                "Retrieval time is not substituted for publication time.",
            ),
        )
        status = (
            CaptureStatus.SUCCESS_WITH_RECORDS if response.content else CaptureStatus.SUCCESS_EMPTY
        )
        return CaptureResult(
            status,
            stored.blob_path,
            stored.manifest_path,
            stored.byte_length,
            stored.sha256,
        )
    except (httpx.HTTPError, OSError, ValueError, ET.ParseError, UnicodeError, csv.Error) as exc:
        return CaptureResult(CaptureStatus.INVALID_CONTENT, None, None, 0, None, str(exc))
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        if own_client:
            http.close()


PUBLIC_ENDPOINTS = {
    "edis_completed_rss": EndpointDefinition(
        "edis_completed_rss",
        "E.DIS Netz GmbH",
        "https://redispatchdaten.de/api/legacy/rss/finished?networkoperator=edi",
        "xml",
        "operator_service_area",
        expected_fields=("guid", "operation_id"),
    ),
    "netztransparenz_redispatch_archive_2013_2020": EndpointDefinition(
        "netztransparenz_redispatch_archive_2013_2020",
        "German TSOs",
        "https://www.netztransparenz.de/xspproxy/api/staticfiles/ntp-relaunch/dokumente/"
        "systemdienstleistungen/betriebsf%C3%BChrung/redispatch/archiv/"
        "2025-09-17%20redispatch%20export%202013-2020.zip",
        "zip",
        "control_area_or_affected_installation",
    ),
    "fifty_hertz_measures_rss": EndpointDefinition(
        "fifty_hertz_measures_rss",
        "50Hertz Transmission GmbH",
        "https://www.50hertz.com/desktopmodules/remit-ma/api/de/9668/rss",
        "xml",
        "tso_control_area",
        expected_fields=("guid", "pub_date_raw"),
    ),
    "fifty_hertz_outage_page": EndpointDefinition(
        "fifty_hertz_outage_page",
        "50Hertz Transmission GmbH",
        "https://www.50hertz.com/Transparency/GridData/Congestionmanagement/OutageandPlanning",
        "html",
        "named_transmission_asset",
    ),
    "stromnetz_berlin_public_load_page": EndpointDefinition(
        "stromnetz_berlin_public_load_page",
        "Stromnetz Berlin GmbH",
        "https://www.stromnetz.berlin/uber-uns/veroffentlichungspflichten/"
        "energiewirtschaftsgesetz-enwg/",
        "html",
        "region_and_voltage_level",
    ),
    "stromnetz_berlin_peak_load_history": EndpointDefinition(
        "stromnetz_berlin_peak_load_history",
        "Stromnetz Berlin GmbH",
        "https://www.stromnetz.berlin/files/globalassets/dokumente/opendata/"
        "veroffentlichungspflichten/historie-jahreshoechstlast-netzlast-berlin.xlsx",
        "xlsx",
        "berlin_region",
    ),
    "stromnetz_berlin_hv_peak_load_history": EndpointDefinition(
        "stromnetz_berlin_hv_peak_load_history",
        "Stromnetz Berlin GmbH",
        "https://www.stromnetz.berlin/files/globalassets/dokumente/opendata/"
        "veroffentlichungspflichten/historie-jahreshoechstlast-hochspannung-berlin.xlsx",
        "xlsx",
        "berlin_high_voltage_level",
    ),
    "stromnetz_berlin_network_structure_history": EndpointDefinition(
        "stromnetz_berlin_network_structure_history",
        "Stromnetz Berlin GmbH",
        "https://www.stromnetz.berlin/files/globalassets/dokumente/opendata/"
        "veroffentlichungspflichten/historie-netzstrukturdaten-berlin.xlsx",
        "xlsx",
        "berlin_region_and_voltage_level",
    ),
    "wesernetz_public_load_page": EndpointDefinition(
        "wesernetz_public_load_page",
        "wesernetz Bremen GmbH",
        "https://www.wesernetz.de/fuer-partner/energielieferanten/stromnetz/"
        "strukturdaten-des-bremer-und-bremerhavener-stromnetzes",
        "html",
        "region_and_voltage_level",
    ),
    "wesernetz_bremen_upstream_load_2025": EndpointDefinition(
        "wesernetz_bremen_upstream_load_2025",
        "wesernetz Bremen GmbH",
        "https://www.wesernetz.de/-/media/wesernetz/downloads-aktuell/fuer-partner/"
        "energielieferanten/stromnetz/strukturdaten/uebergabe-vorgelagertes-netz_2025_hb.csv",
        "csv",
        "bremen_region",
    ),
    "wesernetz_bremerhaven_upstream_load_2025": EndpointDefinition(
        "wesernetz_bremerhaven_upstream_load_2025",
        "wesernetz Bremen GmbH",
        "https://www.wesernetz.de/-/media/wesernetz/downloads-aktuell/fuer-partner/"
        "energielieferanten/stromnetz/strukturdaten/uebergabe-vorgelagertes-netz_2025_bhv.csv",
        "csv",
        "bremerhaven_region",
    ),
    "nrm_public_network_page": EndpointDefinition(
        "nrm_public_network_page",
        "NRM Netzdienste Rhein-Main GmbH",
        "https://www.nrm-netzdienste.de/de/netzzugang/netzzugang-strom",
        "html",
        "operator_service_area_and_planning_area",
    ),
    "fifty_hertz_vertical_grid_load_page": EndpointDefinition(
        "fifty_hertz_vertical_grid_load_page",
        "50Hertz Transmission GmbH",
        "https://www.50hertz.com/en/Transparency/GridData/Gridfigures/VerticalGridLoad",
        "html",
        "tso_control_area",
    ),
    "edis_redispatch_forecast_page": EndpointDefinition(
        "edis_redispatch_forecast_page",
        "E.DIS Netz GmbH",
        "https://www.e-dis-netz.de/de/energie-einspeisen/redispatch-2-0/"
        "einspeisemanagement/veroeffentlichungen/prognose.html",
        "html",
        "operator_service_area_or_published_constraint_location",
    ),
    "smard_download_center": EndpointDefinition(
        "smard_download_center",
        "Bundesnetzagentur | SMARD.de",
        "https://www.smard.de/home/downloadcenter",
        "html",
        "germany_or_published_aggregate",
        licence="CC BY 4.0 subject to dataset metadata",
    ),
    "vnbdigital_edis_network_plan_2024": EndpointDefinition(
        "vnbdigital_edis_network_plan_2024",
        "E.DIS Netz GmbH | VNBdigital",
        "https://www.vnbdigital.de/gateway/files?fileId=6630debe99abd27c97c7cd38&preview=1&serviceName=vnb",
        "pdf",
        "brandenburg_planning_region",
    ),
    "stromnetz_berlin_repartition_page": EndpointDefinition(
        "stromnetz_berlin_repartition_page",
        "Stromnetz Berlin GmbH",
        "https://www.stromnetz.berlin/anschliessen/anschluss-mittel-hochspannung/repartierung/",
        "html",
        "published_allocation_area",
    ),
    "nrm_pro_rata_page": EndpointDefinition(
        "nrm_pro_rata_page",
        "NRM Netzdienste Rhein-Main GmbH",
        "https://www.nrm-netzdienste.de/de/netzanschluss/pro-rata-verfahren-strom",
        "html",
        "frankfurt_operator_service_area",
    ),
    "dwd_hostrada_description": EndpointDefinition(
        "dwd_hostrada_description",
        "Deutscher Wetterdienst",
        "https://opendata.dwd.de/climate_environment/CDC/grids_germany/hourly/hostrada/"
        "DESCRIPTION_gridsgermany_hourly_hostrada_en.pdf",
        "pdf",
        "germany_hourly_grid",
        licence="DWD open-data terms",
    ),
    "simbench_reference_documentation": EndpointDefinition(
        "simbench_reference_documentation",
        "SimBench project consortium",
        "https://simbench.de/wp-content/uploads/2019/08/simbench_documentation_de.pdf",
        "pdf",
        "synthetic_reference_network",
        truth_class="synthetic_benchmark",
    ),
    "entsoe_cgmes_library_page": EndpointDefinition(
        "entsoe_cgmes_library_page",
        "ENTSO-E",
        "https://www.entsoe.eu/data/cim/cim-for-grid-models-exchange/",
        "html",
        "model_exchange_standard",
        truth_class="public_screening",
    ),
}


def write_quality_report(report: dict[str, Any], path: Path) -> None:
    atomic_write(path, (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode())


def verify_regional_manifests(data_root: Path) -> dict[str, object]:
    """Verify every regional snapshot manifest against its durable artifact."""
    checked = 0
    failures = []
    manifests = list((data_root / "raw").rglob("manifest.json"))
    manifests.extend((data_root / "manifests" / "captures").rglob("*.json"))
    for manifest_path in manifests:
        checked += 1
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            relative = manifest.get("blob_path") or manifest.get("storage_path")
            artifact = data_root / relative
            observed = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if observed != manifest["sha256"] or artifact.stat().st_size != manifest["byte_length"]:
                failures.append(str(manifest_path))
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            failures.append(str(manifest_path))
    return {
        "status": "verified" if checked and not failures else "failed",
        "checked_manifests": checked,
        "failures": failures,
    }
