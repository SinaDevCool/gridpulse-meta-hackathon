import json
from pathlib import Path

from capacity_backtest.capacity_study.chronology import build_50hertz_chronology


def test_build_chronology_keeps_context_separate_from_nodal_claim(tmp_path: Path) -> None:
    vertical = tmp_path / "vertical.csv"
    vertical.write_bytes(
        "Datum;von;bis;MW\n01.01.2025;00:00;00:15;-10\n"
        "01.01.2025;00:15;00:30;-6\n".encode("utf-16")
    )
    constraints = tmp_path / "constraints.jsonl"
    constraints.write_text(
        json.dumps({"issue_time": "2025-01-01T00:00:00+00:00", "target_constraint": True})
        + "\n"
    )
    destination = build_50hertz_chronology(vertical, constraints, tmp_path / "data", year=2025)
    row = json.loads((destination / "rows.jsonl").read_text().splitlines()[0])
    quality = json.loads((destination / "quality.json").read_text())
    assert row["vertical_net_load_mw"] == -8
    assert row["constraint_target"] is True
    assert quality["nodal_injections_available"] is False
    assert quality["capacity_claim"] is False
