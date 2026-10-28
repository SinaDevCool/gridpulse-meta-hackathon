from datetime import datetime, timezone

from capacity_backtest.hourly_ac import _active_outage_assets


def test_active_outage_uses_only_latest_published_revision() -> None:
    common = {
        "event_id": "event",
        "network_id": "family",
        "asset_id": "line",
        "starts_at": "2026-01-10T00:00:00+00:00",
    }
    outages = [
        {
            **common,
            "revision": 1,
            "published_at": "2026-01-01T00:00:00+00:00",
            "ends_at": "2026-01-10T08:00:00+00:00",
        },
        {
            **common,
            "revision": 2,
            "published_at": "2026-01-05T00:00:00+00:00",
            "ends_at": "2026-01-10T06:00:00+00:00",
        },
    ]
    assert _active_outage_assets(
        outages, "family", datetime(2026, 1, 10, 5, tzinfo=timezone.utc)
    ) == ["line"]
    assert not _active_outage_assets(
        outages, "family", datetime(2026, 1, 10, 7, tzinfo=timezone.utc)
    )
