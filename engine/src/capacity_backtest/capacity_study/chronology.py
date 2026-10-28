"""Build an auditable annual control-area chronology from captured operator data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from capacity_backtest.storage import atomic_write, file_sha256


def build_50hertz_chronology(
    vertical_load_csv: Path,
    constraint_rows: Path,
    data_root: Path,
    *,
    year: int,
) -> Path:
    """Combine 15-minute vertical net load and hourly constraint context."""
    intervals: dict[str, list[float]] = defaultdict(list)
    content = vertical_load_csv.read_bytes().decode("utf-16")
    for row in csv.reader(io.StringIO(content), delimiter=";"):
        if len(row) < 4 or row[0] in {"", "Maximum", "Minimum", "Datum"}:
            continue
        try:
            parsed_stamp = datetime.strptime(f"{row[0]} {row[1]}", "%d.%m.%Y %H:%M").replace(
                tzinfo=ZoneInfo("Europe/Berlin")
            )
            value = float(row[3].replace(",", "."))
        except ValueError:
            continue
        if parsed_stamp.year == year:
            intervals[parsed_stamp.strftime("%Y-%m-%dT%H:00:00")].append(value)
    constraints = {}
    with constraint_rows.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            constraint_stamp = str(row.get("issue_time", ""))
            if constraint_stamp.startswith(str(year)):
                constraints[constraint_stamp[:13]] = {
                    "constraint_target": row.get("target_constraint"),
                    "redispatch_mw_lag_1h": row.get("redispatch_mw_lag_1h"),
                    "source_available": row.get("source_available"),
                }
    input_hashes = [file_sha256(vertical_load_csv), file_sha256(constraint_rows)]
    dataset_id = hashlib.sha256(("|".join(input_hashes) + f"|{year}").encode()).hexdigest()
    destination = data_root / "features" / "50hertz-annual-chronology-v1" / dataset_id
    rows = []
    incomplete = 0
    observed = {stamp: sum(values) / len(values) for stamp, values in intervals.items()}
    calendar = [
        (datetime(year, 1, 1, tzinfo=ZoneInfo("Europe/Berlin")) + timedelta(hours=index)).strftime(
            "%Y-%m-%dT%H:00:00"
        )
        for index in range(8760)
    ]
    available_indexes = [index for index, stamp in enumerate(calendar) if stamp in observed]
    for index, hour_stamp in enumerate(calendar):
        values = intervals.get(hour_stamp, [])
        incomplete += len(values) != 4
        is_observed = hour_stamp in observed
        if is_observed:
            value = observed[hour_stamp]
            method = None
        else:
            nearest = min(available_indexes, key=lambda candidate: abs(candidate - index))
            value = observed[calendar[nearest]]
            method = "nearest-observed-hour"
        context = constraints.get(hour_stamp[:13], {})
        rows.append(
            {
                "timestamp_local": hour_stamp,
                "vertical_net_load_mw": value,
                "quarter_hour_count": len(values),
                "value_observed": is_observed,
                "imputation_method": method,
                **context,
                "truth_class": "operator_published_context",
                "geographic_resolution": "50hertz_control_area",
            }
        )
    atomic_write(
        destination / "rows.jsonl",
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode(),
    )
    quality = {
        "schema_version": "50hertz-annual-chronology-quality-v1",
        "dataset_id": dataset_id,
        "year": year,
        "hour_count": len(rows),
        "expected_hours_non_dst_adjusted": 8760,
        "incomplete_quarter_hour_groups": incomplete,
        "imputed_hours": sum(not row["value_observed"] for row in rows),
        "constraint_context_hours": sum("constraint_target" in row for row in rows),
        "input_hashes": input_hashes,
        "capacity_claim": False,
        "nodal_injections_available": False,
        "limitations": [
            "Vertical net load is a signed 50Hertz control-area exchange, not gross demand.",
            "Local timestamps do not disambiguate the autumn DST fold.",
            "No public mapping allocates these values to the static-model buses.",
        ],
    }
    atomic_write(destination / "quality.json", (json.dumps(quality, indent=2) + "\n").encode())
    return destination
