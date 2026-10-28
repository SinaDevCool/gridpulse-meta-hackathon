from datetime import datetime, timezone

from capacity_backtest.fifty_hertz import known_measures, measure_quality, normalize_measures


def record(revision: int, published: str, increase: int, reduction: int):
    return {
        "pub_date_raw": published,
        "description_raw": (
            f"Datum: 15.08.2026<br>von - bis: 06:00 - 06:15<br>Erh�hung: {increase}<br>"
            f"Reduktion: {reduction}<br>ID: Redispatch_20260815040000_{revision:03d}"
        ),
        "link": "https://www.50hertz.com/example",
    }


def test_50hertz_revision_selection_is_publication_time_aware() -> None:
    records = [
        record(1, "Sat, 15 Aug 2026 06:30:00 +0200", 0, 0),
        record(2, "Sat, 15 Aug 2026 07:00:00 +0200", 0, 165),
    ]
    measures = normalize_measures(records)
    assert measures[0].starts_at == datetime(2026, 8, 15, 4, tzinfo=timezone.utc)
    issue = datetime(2026, 8, 15, 4, 45, tzinfo=timezone.utc)
    assert known_measures(measures, issue)[0].revision == 1
    assert (
        known_measures(measures, datetime(2026, 8, 15, 5, 1, tzinfo=timezone.utc))[0].reduction_mw
        == 165
    )


def test_50hertz_quality_reports_observed_but_incomplete_revision_chain() -> None:
    measures = normalize_measures(
        [
            record(1, "Sat, 15 Aug 2026 06:30:00 +0200", 0, 0),
            record(2, "Sat, 15 Aug 2026 07:00:00 +0200", 0, 165),
        ]
    )
    report = measure_quality(measures, snapshot_hash="a" * 64)
    assert report["unique_intervals"] == 1
    assert report["revised_intervals"] == 1
    assert report["active_final_intervals"] == 1
    assert report["publication_time_validated"] is True
    assert report["training_admitted"] is False
