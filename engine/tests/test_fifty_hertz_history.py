from datetime import date, datetime, timezone

import capacity_backtest.fifty_hertz_history as history

PAGE = """
<div class="rma-data-timeslots"><ul>
<li id="Redispatch_20240114230000_004">
  <div class="rma-data-timeslot-item rma-data-timeslot-date"><label>Datum</label><div>15.01.2024</div></div>
  <div class="rma-data-timeslot-item rma-data-timeslot-time"><label>von - bis</label><div>00:00 - 00:15</div></div>
  <div class="rma-data-timeslot-value"><label>Erh\u00f6hung</label><div><span>0</span></div></div>
  <div class="rma-data-timeslot-value"><label>Reduktion</label><div><span class="rma-changed-value">1.409,5</span></div></div>
  <div class="rma-data-timeslot-item rma-data-timeslot-creationdate"><label>Erzeugungsdatum</label><div>14.01.2024 23:48</div></div>
  <div class="rma-data-timeslot-item rma-data-timeslot-versionid"><label>ID</label><div><span>Redispatch_20240114230000_004</span></div></div>
</li></ul></div>
""".encode()


def test_history_parser_preserves_utc_interval_publication_and_revision() -> None:
    records, warnings = history.parse_history_page(PAGE)
    assert warnings == []
    assert len(records) == 1
    record = records[0]
    assert record.interval_start == datetime(2024, 1, 14, 23, tzinfo=timezone.utc)
    assert record.published_at == datetime(2024, 1, 14, 22, 48, tzinfo=timezone.utc)
    assert record.revision == 4
    assert record.increase_mw == 0
    assert record.reduction_mw == 1409.5
    events = record.events(
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        snapshot_hash="a" * 64,
        source_url="https://example.test",
    )
    assert {event.direction for event in events} == {"up", "down"}
    assert all(event.geographic_resolution.value == "control_area" for event in events)


def test_history_profile_does_not_promote_observed_revisions_to_complete_archive() -> None:
    records, warnings = history.parse_history_page(PAGE)
    profile = history.profile_history_page(
        records, warnings, requested_date=date(2024, 1, 15), snapshot_hash="a" * 64
    )
    assert profile["revision_history_observed"] is True
    assert profile["revision_history_complete"] is False
    assert profile["training_admitted"] is False
    assert profile["selected_date_matches"] is True


def test_ambiguous_publication_time_is_quarantined() -> None:
    page = PAGE.replace(b"14.01.2024 23:48", b"26.10.2025 02:30")
    records, warnings = history.parse_history_page(page)
    assert records == []
    assert "ambiguous Europe/Berlin" in warnings[0]


def test_official_csv_is_explicitly_latest_revision_only() -> None:
    payload = (
        "Datum;von (UTC);bis (UTC);Erhöhung;Reduktion;Erzeugungsdatum (UTC);ID\n"
        "15.01.2024;00:00;00:15;0;1245;14.01.2024 22:48;"
        "Redispatch_20240115000000_003\n"
    ).encode()
    records = history.parse_history_csv(payload)
    assert len(records) == 1
    assert records[0].revision == 3
    assert records[0].interval_start == datetime(2024, 1, 15, tzinfo=timezone.utc)
    assert records[0].reduction_mw == 1245
