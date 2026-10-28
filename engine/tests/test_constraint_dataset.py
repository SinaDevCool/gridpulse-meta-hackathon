from datetime import datetime, timedelta, timezone

from capacity_backtest.constraint_dataset import _known_value, _timeline
from capacity_backtest.fifty_hertz_history import HistoricalMeasure


def measure(revision: int, published: datetime, power: float) -> HistoricalMeasure:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return HistoricalMeasure(
        record_id=f"Redispatch_20250101000000_{revision:03d}",
        interval_start=start,
        interval_end=start + timedelta(minutes=15),
        published_at=published,
        revision=revision,
        increase_mw=power,
        reduction_mw=0,
        displayed_date="01.01.2025",
        displayed_interval="00:00 - 00:15",
        publication_time_raw=published.isoformat(),
    )


def test_constraint_features_cannot_see_later_revision() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    timeline = _timeline(
        [measure(1, start - timedelta(hours=1), 10), measure(2, start + timedelta(hours=1), 30)]
    )
    assert _known_value(timeline, start) == 10
    assert _known_value(timeline, start + timedelta(hours=2)) == 30
