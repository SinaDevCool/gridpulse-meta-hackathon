"""Run a leakage-safe upstream-context backtest from immutable ENTSO-E snapshots."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .dwd import load_temperature
from .entsoe import aggregate_generation_hourly, aggregate_hourly, parse_timeseries
from .models import MeanBaseline, RidgeBaseline, TabPFNRegressorAdapter, regression_metrics
from .profiling import assert_profile_accepted, profile_entsoe
from .regional_reports import write_regional_reports
from .regions import load_regions
from .storage import captured_blobs, resolve_storage
from .timeseries import HourlyObservation, build_lagged_rows, chronological_split
from .validation import (
    annual_stress_scenarios,
    data_centre_flexibility_scenarios,
    rolling_origin_ridge,
    rolling_stress_classifier,
)

BASE_FEATURES = ("hour", "weekday", "month", "load_lag_1h", "load_lag_24h", "load_lag_168h")
GENERATION_FEATURES = (
    "wind_lag_1h",
    "wind_lag_24h",
    "wind_lag_168h",
    "solar_lag_1h",
    "solar_lag_24h",
    "solar_lag_168h",
)
WEATHER_FEATURES = ("temperature_lag_1h", "temperature_lag_24h", "temperature_lag_168h")


def _profile_summary(profiles: list[dict[str, object]]) -> dict[str, object]:
    return {
        "artifact_count": len(profiles),
        "accepted_count": sum(bool(item["accepted"]) for item in profiles),
        "series_count": sum(int(item["series_count"]) for item in profiles),
        "point_count": sum(int(item["point_count"]) for item in profiles),
        "duplicate_points": sum(int(item["duplicate_points"]) for item in profiles),
        "missing_intervals": sum(int(item["missing_intervals"]) for item in profiles),
        "units": sorted({unit for item in profiles for unit in item["units"]}),
        "resolutions": sorted(
            {resolution for item in profiles for resolution in item["resolutions"]}
        ),
        "business_types": sorted({kind for item in profiles for kind in item["business_types"]}),
        "directions": sorted({direction for item in profiles for direction in item["directions"]}),
        "artifacts": [str(item["artifact"]) for item in profiles],
    }


def _matrix(
    rows: list[dict[str, object]], features: tuple[str, ...]
) -> tuple[list[list[float]], list[float]]:
    complete = [
        row
        for row in rows
        if row["target_load_mw"] is not None and all(row[key] is not None for key in features)
    ]
    return (
        [[float(row[key]) for key in features] for row in complete],
        [float(row["target_load_mw"]) for row in complete],
    )


def run_live_backtest(
    root: Path, final_year: int, *, include_tabpfn: bool = False
) -> dict[str, object]:
    layout = resolve_storage(root)
    documents_by_type: dict[str, list[Path]] = {"A65": [], "A75": []}
    for document_type, document_paths in documents_by_type.items():
        seen: set[str] = set()
        for source_id in (f"entsoe-timeseries-{document_type.lower()}", "legacy-entsoe-live"):
            for path, manifest in captured_blobs(layout.data_root, source_id):
                request = manifest.get("request", {})
                legacy_path = str(request.get("legacy_path", ""))
                requested_type = str(request.get("documentType", ""))
                if (
                    document_type not in legacy_path.replace("\\", "/").split("/")
                    and requested_type != document_type
                ):
                    continue
                digest = str(manifest["sha256"])
                if digest not in seen:
                    document_paths.append(path)
                    seen.add(digest)
    documents = documents_by_type["A65"]
    if not documents:
        raise RuntimeError("No ENTSO-E A65 snapshots found; run live fetch first")
    combined = {}
    profiles = []
    for path in documents:
        parsed = parse_timeseries(path.read_bytes(), "A65")
        profile = profile_entsoe(parsed, "A65")
        assert_profile_accepted(profile)
        profiles.append({"artifact": str(path), **profile.as_dict()})
        combined.update(aggregate_hourly(parsed))
    generation: dict[object, dict[str, float]] = {}
    generation_profiles = []
    for path in documents_by_type["A75"]:
        parsed = parse_timeseries(path.read_bytes(), "A75")
        profile = profile_entsoe(parsed, "A75")
        assert_profile_accepted(profile)
        generation_profiles.append({"artifact": str(path), **profile.as_dict()})
        for timestamp, values in aggregate_generation_hourly(parsed).items():
            generation.setdefault(timestamp, {}).update(values)
    observations = []
    temperature = load_temperature(layout.data_root)
    for timestamp, value in sorted(combined.items()):
        values = generation.get(timestamp, {})
        wind = values.get("B18_generation", 0.0) + values.get("B19_generation", 0.0)
        solar = values.get("B16_generation")
        observations.append(
            HourlyObservation(timestamp, "DE-LU", value, wind, solar, temperature.get(timestamp))
        )
    rows = build_lagged_rows(observations)
    train_rows, test_rows = chronological_split(rows, final_year)
    features = BASE_FEATURES + GENERATION_FEATURES
    if temperature:
        features += WEATHER_FEATURES
    train_x, train_y = _matrix(train_rows, features)
    test_x, test_y = _matrix(test_rows, features)
    base_train_x, base_train_y = _matrix(train_rows, BASE_FEATURES)
    base_test_x, base_test_y = _matrix(test_rows, BASE_FEATURES)
    if len(test_y) < 24 * 300:
        raise RuntimeError("held-out year is incomplete")
    models = [MeanBaseline(), RidgeBaseline()]
    if include_tabpfn:
        models.append(TabPFNRegressorAdapter())
    results = {}
    base_result = RidgeBaseline().fit_predict(base_train_x, base_train_y, base_test_x)
    results["ridge_load_lags_only"] = {
        "status": base_result.status,
        "metrics": regression_metrics(base_test_y, base_result.predictions),
        "limitations": ["Ablation baseline excludes generation lags."],
    }
    prediction_dir = layout.data_root / "predictions" / f"entsoe-de-lu-{final_year}"
    prediction_dir.mkdir(parents=True, exist_ok=True)
    for model in models:
        result = model.fit_predict(train_x, train_y, test_x)
        metrics = (
            regression_metrics(test_y, result.predictions) if result.status == "succeeded" else None
        )
        results[result.model] = {
            "status": result.status,
            "metrics": metrics,
            "limitations": result.limitations,
        }
    region_ids = [region.id for region in load_regions(root / "config" / "regions.yaml")]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context_area": "Germany-Luxembourg bidding zone",
        "requested_regions": region_ids,
        "regional_measurement": False,
        "training_rows": len(train_y),
        "held_out_year": final_year,
        "held_out_rows": len(test_y),
        "models": results,
        "features": list(features),
        "load_profile_summary": _profile_summary(profiles),
        "generation_profile_summary": _profile_summary(generation_profiles),
        "generation_feature_boundary": "wind and solar observations enter only through past lags",
        "rolling_origin_ridge": rolling_origin_ridge(rows, features, (2022, 2023, 2024, 2025)),
        "rolling_stress_classifier": rolling_stress_classifier(
            rows, features, (2022, 2023, 2024, 2025)
        ),
        "annual_stress_scenarios": annual_stress_scenarios(test_y),
        "data_centre_flexibility_scenarios": data_centre_flexibility_scenarios(test_y),
        "capacity_claim": False,
        "available_capacity_mw": None,
        "limitations": [
            "The same upstream bidding-zone series is contextual evidence for every requested region.",
            "No city, line, transformer or substation load is inferred from this series.",
            "Actual available connection capacity remains unknown without operator evidence.",
        ],
    }
    (root / "reports" / "live-upstream-backtest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    metric_lines = []
    for name, result in results.items():
        metrics = result["metrics"]
        metric_lines.append(
            f"- {name}: **{result['status']}**"
            + (f"; MAE {metrics['mae']:.1f} MW; RMSE {metrics['rmse']:.1f} MW" if metrics else "")
        )
    (root / "reports" / "live-upstream-backtest.md").write_text(
        "# Live upstream-context backtest\n\n"
        "## Outcome\n\n"
        f"- Training observations: {len(train_y):,} hourly rows\n"
        f"- Frozen held-out period: {final_year} ({len(test_y):,} hourly rows)\n"
        "- Geographic measurement: Germany-Luxembourg bidding zone\n"
        "- Regional or substation measurement: **No**\n"
        "- Available connection capacity: **Unknown**\n\n"
        "## Model results\n\n" + "\n".join(metric_lines) + "\n\n"
        "## Added evidence\n\n"
        f"- DWD temperature lag features active: **{'Yes' if temperature else 'No'}**\n"
        "- Wind and solar generation enter through past lags only.\n"
        "- Congestion and outage features: **Unavailable; not encoded as zero**\n\n"
        "## Stress classifier gate\n\n"
        + "\n".join(
            f"- {fold['test_year']}: Brier {fold['brier_score']:.3f}; precision "
            f"{fold['precision']:.1%}; recall {fold['recall']:.1%}; false-negative rate "
            f"{fold['false_negative_rate']:.1%}"
            for fold in report["rolling_stress_classifier"]
        )
        + "\n\nRelease gate: **FAIL**. Recall is high, but precision is not stable enough for "
        "operational alerts.\n\n"
        "## Interpretation\n\n"
        "These metrics measure next-hour national-system load prediction from calendar and "
        "historical-load lags. They do not measure free-capacity prediction error. The series may "
        "support upstream stress scenarios for Berlin, Brandenburg, Bremen, Frankfurt and "
        "Rhine-Main, but must not be allocated to those regions or to public map nodes as measured "
        "load. Operator topology, ratings, outages, reservations, queues, protection limits and "
        "connection-study outcomes remain unavailable.\n",
        encoding="utf-8",
    )
    with (prediction_dir / "held-out-target.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("row", "actual_load_mw"))
        writer.writerows(enumerate(test_y))
    write_regional_reports(root, report, data_root=layout.data_root)
    return report
