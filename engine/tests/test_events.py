from datetime import datetime, timedelta, timezone

from capacity_backtest.events import GridEvent, event_features


def test_future_revision_is_not_leaked_into_historical_features():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    evidence = {
        "source_id": "source",
        "source_record_id": "record",
        "retrieved_at": now,
        "source_url": "https://example.test/events",
        "snapshot_hash": "a" * 64,
    }
    base = GridEvent(
        "x",
        now - timedelta(hours=1),
        now,
        now + timedelta(hours=2),
        "TSO",
        "DE",
        "outage",
        None,
        50,
        None,
        1,
        **evidence,
    )
    revision = GridEvent(
        "x",
        now + timedelta(hours=1),
        now,
        now + timedelta(hours=2),
        "TSO",
        "DE",
        "outage",
        None,
        80,
        None,
        2,
        **evidence,
    )
    assert event_features([base, revision], now)["active_known_power_mw"] == 50


def test_unknown_event_power_is_not_coerced_to_zero():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    event = GridEvent(
        "x",
        now - timedelta(hours=1),
        now,
        now + timedelta(hours=2),
        "TSO",
        "DE",
        "outage",
        None,
        None,
        None,
        1,
        source_id="source",
        source_record_id="record",
        retrieved_at=now,
        source_url="https://example.test/events",
        snapshot_hash="a" * 64,
    )
    assert event_features([event], now)["active_known_power_mw"] is None
