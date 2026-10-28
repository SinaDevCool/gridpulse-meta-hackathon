import json
from pathlib import Path

from capacity_backtest.constraint_model import FEATURES, _load, _reliability, _season


def test_reliability_bins_preserve_counts() -> None:
    bins = _reliability([0, 1, 1, 0], [0.1, 0.8, 0.9, 0.2])
    assert sum(item["count"] for item in bins) == 4
    assert _season(1) == "winter"
    assert _season(7) == "summer"


def test_load_excludes_unknown_targets_and_unavailable_features(tmp_path: Path) -> None:
    complete = {
        "issue_time": "2025-01-01T00:00:00+00:00",
        "target_constraint": True,
        **{name: 1 for name in FEATURES},
    }
    unknown_target = {**complete, "target_constraint": None}
    missing_feature = {**complete, FEATURES[-1]: None}
    path = tmp_path / "rows.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in (complete, unknown_target, missing_feature)) + "\n"
    )
    rows = _load(path)
    assert len(rows) == 1
    assert rows[0]["target_constraint"] is True
