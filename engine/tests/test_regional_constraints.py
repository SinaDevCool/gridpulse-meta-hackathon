from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from capacity_backtest.admissibility import AdmissionDecision, require_training_admission
from capacity_backtest.events import GeographicResolution, GridEvent, known_events
from capacity_backtest.regional_constraints import (
    RegionalHourlyRow,
    build_regional_rows,
    rolling_event_rate,
    rolling_logistic,
    rolling_seasonal_rate,
)


def event(now, *, revision=1, published_offset=-2, power=10.0, event_id="e1"):
    return GridEvent(
        event_id,
        now + timedelta(hours=published_offset),
        now + timedelta(hours=1),
        now + timedelta(hours=3),
        "E.DIS Netz",
        "DE-BB",
        "redispatch",
        "down",
        power,
        None,
        revision,
        source_id="edis_completed",
        source_record_id=event_id,
        retrieved_at=now,
        region="DE-BB",
        geographic_resolution=GeographicResolution.BUNDESLAND,
        source_url="https://www.e-dis-netz.de/",
        snapshot_hash="a" * 64,
    )


def test_canonical_event_validates_unknowns_and_timezone():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    record = event(now, power=None)
    assert record.as_dict()["power_mw"] is None
    with pytest.raises(ValueError, match="timezone-aware"):
        GridEvent(
            "x",
            now.replace(tzinfo=None),
            now,
            now + timedelta(hours=1),
            "operator",
            "area",
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
        ).validate()
    with pytest.raises(ValueError, match="identity"):
        GridEvent(
            "x",
            now,
            now,
            now + timedelta(hours=1),
            "operator",
            "area",
            "outage",
            None,
            None,
            None,
            1,
            retrieved_at=now,
        ).validate()


def test_revision_selection_uses_publication_time_and_source_identity():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    early = event(now, revision=1, published_offset=-2, power=10)
    future = event(now, revision=2, published_offset=2, power=20)
    assert known_events([future, early], now)[0].power_mw == 10


def test_daylight_saving_fold_is_preserved_when_normalized_to_utc():
    berlin = ZoneInfo("Europe/Berlin")
    first = datetime(2025, 10, 26, 2, 0, tzinfo=berlin, fold=0)
    second = datetime(2025, 10, 26, 2, 0, tzinfo=berlin, fold=1)
    record = GridEvent(
        "dst",
        first - timedelta(hours=1),
        first,
        second,
        "operator",
        "DE-BE",
        "outage",
        None,
        None,
        None,
        1,
        source_id="source",
        source_record_id="record",
        retrieved_at=second,
        source_url="https://example.test/events",
        snapshot_hash="a" * 64,
    )
    payload = record.as_dict()
    assert payload["starts_at"] == "2025-10-26T00:00:00+00:00"
    assert payload["ends_at"] == "2025-10-26T01:00:00+00:00"


def test_missing_source_keeps_target_unknown():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    row = build_regional_rows(
        [now], [event(now)], "DE-BB", source_available=False, revision_complete=False
    )[0]
    assert row.target_event is None
    assert row.source_available is False


def test_rolling_baseline_is_strictly_prior_period():
    start = datetime(2023, 12, 31, 22, tzinfo=timezone.utc)
    rows = build_regional_rows(
        [start + timedelta(hours=i) for i in range(5)],
        [event(start, published_offset=-1)],
        "DE-BB",
        horizon_hours=2,
        source_available=True,
        revision_complete=True,
    )
    fold = rolling_event_rate(rows, [2024])[0]
    assert fold["training_rows"] == 2
    assert fold["test_rows"] == 3
    assert rolling_seasonal_rate(rows, [2024])[0]["model"] == "seasonal_calendar_baseline"


def test_admissibility_fails_closed():
    decision = AdmissionDecision(
        "source",
        "regional context",
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        False,
        "publication archive unavailable",
    )
    with pytest.raises(ValueError, match="not admitted"):
        require_training_admission(decision)


def test_logistic_calibration_uses_prior_period_only():
    rows = []
    for year in (2023, 2024):
        for hour in range(120):
            target = hour % 5 == 0
            rows.append(
                RegionalHourlyRow(
                    datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour),
                    "DE-BB",
                    24,
                    int(target),
                    hour % 7,
                    None,
                    int(target),
                    True,
                    True,
                    target,
                    "bundesland",
                )
            )
    folds = rolling_logistic(rows, [2024])
    assert {fold["calibration"] for fold in folds} == {"sigmoid", "isotonic"}
    assert all(fold["training_rows"] + fold["calibration_rows"] == 120 for fold in folds)
