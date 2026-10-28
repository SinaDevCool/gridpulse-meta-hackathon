import hashlib
import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import httpx

from capacity_backtest.regional_ingest import (
    CaptureStatus,
    EndpointDefinition,
    capture_endpoint,
    parse_delimited,
    parse_edis_rss,
    profile_artifact,
    profile_netztransparenz_archive,
    profile_records,
    verify_regional_manifests,
)

RSS = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'><channel><item>
<guid>redispatchdaten.de:finished:operation:14853203</guid>
<title>Completed operation</title><pubDate>Sun, 16 Aug 2026 10:00:00 GMT</pubDate>
<description>Einsatz-ID: FBR-26-0001&lt;br /&gt;Gebiet: Brandenburg&lt;br /&gt;Ort Engpass: Testort&lt;br /&gt;AnlagenschlÃ¼ssel: SR-1</description>
</item></channel></rss>""".encode()


def endpoint(**kwargs) -> EndpointDefinition:
    values = {
        "source_id": "fixture",
        "publisher": "Operator",
        "url": "https://example.test/feed",
        "format": "xml",
        "geographic_resolution": "operator_service_area",
        "expected_fields": ("guid", "operation_id"),
    }
    values.update(kwargs)
    return EndpointDefinition(**values)


def test_edis_rss_preserves_raw_publication_field_without_promoting_it() -> None:
    records = parse_edis_rss(RSS)
    assert records[0]["guid"].endswith("14853203")
    assert records[0]["operation_id"] == "FBR-26-0001"
    assert "published_at" not in records[0]
    report = profile_records(endpoint(), records, snapshot_hash="a" * 64)
    assert report["publication_time_validated"] is False
    assert report["training_admitted"] is False


def test_delimited_parser_does_not_sum_or_coerce_units() -> None:
    records = parse_delimited(b"BEGINN;MITTLERE_LEISTUNG_MW\n2025-01-01;12,5\n")
    assert records == [{"BEGINN": "2025-01-01", "MITTLERE_LEISTUNG_MW": "12,5"}]


def test_netztransparenz_archive_is_profiled_but_not_training_admitted() -> None:
    header = (
        "BEGINN_DATUM;BEGINN_UHRZEIT;ZEITZONE_VON;ENDE_DATUM;ENDE_UHRZEIT;"
        "ZEITZONE_BIS;RICHTUNG;MITTLERE_LEISTUNG_MW;MAXIMALE_LEISTUNG_MW;"
        "GESAMTE_ARBEIT_MWH;ANWEISENDER_UENB;ANFORDERNDER_UENB;BETROFFENE_ANLAGE\n"
    )
    row = "02.04.2013;11:00;UTC;02.04.2013;14:00;UTC;reduce;267;300;800;50Hertz;PSE;Plant\n"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("redispatch.csv", header + row)
    report = profile_netztransparenz_archive(buffer.getvalue(), snapshot_hash="b" * 64)
    assert report["record_count"] == 1
    assert report["coverage_start"] == "2013-04-02"
    assert report["units_validated"] is True
    assert report["revision_history_complete"] is False
    assert report["training_admitted"] is False


def test_capture_uses_staging_and_writes_verified_manifest(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=RSS, headers={"ETag": '"v1"', "Content-Type": "application/rss+xml"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = capture_endpoint(
        endpoint(),
        tmp_path / "cloud",
        tmp_path / "work",
        client=client,
        retrieved_at=datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
    )
    assert result.status == CaptureStatus.SUCCESS_WITH_RECORDS
    assert result.artifact_path.read_bytes() == RSS
    assert result.sha256 == hashlib.sha256(RSS).hexdigest()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["retrieved_at"] == "2026-08-16T12:00:00+00:00"
    assert manifest["response_headers"]["etag"] == '"v1"'
    assert not any((tmp_path / "work" / "staging").iterdir())
    assert verify_regional_manifests(tmp_path / "cloud") == {
        "status": "verified",
        "checked_manifests": 1,
        "failures": [],
    }


def test_capture_distinguishes_empty_auth_and_rate_limit(tmp_path: Path) -> None:
    for code, expected in (
        (200, CaptureStatus.SUCCESS_EMPTY),
        (401, CaptureStatus.AUTHENTICATION_FAILED),
        (429, CaptureStatus.RATE_LIMITED),
        (503, CaptureStatus.SOURCE_UNAVAILABLE),
    ):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request, status=code: httpx.Response(status))
        )
        result = capture_endpoint(endpoint(), tmp_path / "cloud", tmp_path / "work", client=client)
        assert result.status == expected


def test_non_tabular_publication_profile_never_admits_training() -> None:
    source = endpoint(format="html")
    report = profile_artifact(source, b"<!doctype html><html></html>", snapshot_hash="a" * 64)
    assert report["format_signature_valid"] is True
    assert report["training_admitted"] is False
    assert report["zero_semantics_validated"] is False
