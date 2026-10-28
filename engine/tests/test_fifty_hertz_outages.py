from datetime import datetime, timezone

import capacity_backtest.fifty_hertz_outages as outages

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><item>
<guid>https://www.50hertz.com/de/path/Id/104741/Version/142873</guid>
<title>Revisionsplanung, geändert</title>
<description>&lt;table&gt;
&lt;tr&gt;&lt;th&gt;Beginn:&lt;/th&gt;&lt;td&gt;08/13/2026 06:00:00&lt;/td&gt;&lt;/tr&gt;
&lt;tr&gt;&lt;th&gt;Ende:&lt;/th&gt;&lt;td&gt;08/15/2026 17:00:00&lt;/td&gt;&lt;/tr&gt;
&lt;tr&gt;&lt;th&gt;Spannungsebene:&lt;/th&gt;&lt;td&gt;380-KV&lt;/td&gt;&lt;/tr&gt;
&lt;tr&gt;&lt;th&gt;Netzelement:&lt;/th&gt;&lt;td&gt;380-kV-Ltg Rö-Hr 446&lt;/td&gt;&lt;/tr&gt;
&lt;tr&gt;&lt;th&gt;Revisionsplanungs-ID:&lt;/th&gt;&lt;td&gt;D8-1355/2026_2&lt;/td&gt;&lt;/tr&gt;
&lt;tr&gt;&lt;th&gt;Marktgebiet:&lt;/th&gt;&lt;td&gt;50Hertz-Regelzone&lt;/td&gt;&lt;/tr&gt;
&lt;tr&gt;&lt;th&gt;Beeinträchtigte Kapazität:&lt;/th&gt;&lt;td&gt;100%&lt;/td&gt;&lt;/tr&gt;
&lt;tr&gt;&lt;th&gt;Grund:&lt;/th&gt;&lt;td&gt;Wartung/Umbau&lt;/td&gt;&lt;/tr&gt;
&lt;/table&gt;</description>
<pubDate>Sat, 15 Aug 2026 17:03:34 +0000</pubDate>
</item></channel></rss>""".encode()


def test_outage_feed_preserves_asset_revision_and_unknown_mw() -> None:
    events = outages.parse_outage_rss(
        RSS,
        retrieved_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        snapshot_hash="a" * 64,
    )
    assert len(events) == 1
    event = events[0]
    assert event.event_id == "50hertz-outage-104741"
    assert event.revision == 2
    assert event.power_mw is None
    assert event.affected_asset_ids == ("380-kV-Ltg Rö-Hr 446",)
    assert event.geographic_resolution.value == "asset"
    assert event.published_at == datetime(2026, 8, 15, 17, 3, 34, tzinfo=timezone.utc)
