import io
import zipfile
from datetime import datetime, timezone

from capacity_backtest import entsoe_events

DOCUMENT = b"""<Unavailability_MarketDocument xmlns="urn:test">
<mRID>document-1</mRID><revisionNumber>10</revisionNumber><type>A78</type>
<createdDateTime>2025-11-27T13:07:36Z</createdDateTime>
<unavailability_Time_Period.timeInterval><start>2024-03-19T06:00Z</start><end>2026-09-01T16:00Z</end></unavailability_Time_Period.timeInterval>
<TimeSeries><businessType>A53</businessType><Asset_RegisteredResource>
<mRID>11T0-0000-0979-2</mRID><name>Stendal/West - Wolmirstedt 487</name>
<location.name>Stendal/West - Wolmirstedt</location.name>
</Asset_RegisteredResource></TimeSeries></Unavailability_MarketDocument>"""


def archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as output:
        output.writestr("001-outage.xml", DOCUMENT)
    return buffer.getvalue()


def test_a78_zip_preserves_document_revision_and_asset_identity() -> None:
    events = entsoe_events.parse_a78_zip(
        archive(),
        retrieved_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        snapshot_hash="a" * 64,
    )
    assert len(events) == 1
    event = events[0]
    assert event.event_id == "document-1"
    assert event.revision == 10
    assert event.affected_asset_ids == ("11T0-0000-0979-2",)
    assert event.power_mw is None
    assert event.geographic_resolution.value == "asset"
