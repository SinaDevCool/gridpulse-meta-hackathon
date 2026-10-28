"""Command-line interface for source capture and evidence auditing."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from grid_data.berlin_synthetic_capacity import build_berlin_synthetic_model

from .audit import write_audit
from .backtest import load_study, run_and_write
from .capacity_study.runner import run_capacity_study
from .cgmes import inspect_cgmes_package
from .constraint_dataset import build_constraint_dataset
from .constraint_model import run_constraint_models
from .contingency_v4 import run_contingency_v4_audit, write_contingency_audit
from .download import fetch_source, verify_snapshot
from .dwd import fetch_weather
from .entsoe import fetch_document
from .entsoe_events import capture_a63_probe, capture_a78_probe
from .fifty_hertz import measure_quality, normalize_measures
from .fifty_hertz_history import capture_history_csv, capture_history_dates, parse_history_csv
from .fifty_hertz_outages import capture_outage_rss
from .fifty_hertz_vertical import capture_vertical_load_archive
from .graph_export import export_neo4j_csv
from .gridcare_outputs import unavailable_gridcare_output
from .hourly_ac import run_representative_hourly_ac, write_hourly_ac
from .live_backtest import run_live_backtest
from .network_contracts import load_network_package
from .operator_reconciliation import reconcile_connection_outcomes, validate_operator_intake
from .optimized_deflex import run_optimized_deflex_benchmark, write_optimized_deflex
from .queue_backtest import build_queue_feature_rows, run_queue_backtest, write_queue_artifacts
from .regional_ingest import (
    PUBLIC_ENDPOINTS,
    capture_endpoint,
    parse_edis_rss,
    parse_generic_rss,
    profile_artifact,
    profile_netztransparenz_archive,
    profile_records,
    verify_regional_manifests,
    write_quality_report,
)
from .regional_load import profile_berlin_load_workbook, profile_wesernetz_load_csv
from .registry import load_registry, registry_by_id
from .storage import (
    atomic_write,
    captured_blobs,
    compact_legacy_cloud_snapshots,
    initialise_storage,
    migrate_legacy_data,
    resolve_storage,
    storage_health,
    storage_inventory,
)
from .synthetic_operator import (
    SyntheticOperatorConfig,
    benchmark_records_from_report,
    build_synthetic_operator_package,
    verify_synthetic_operator_package,
)
from .territory.backtest import (
    HistoricalOperatorCase,
    OperatorPrediction,
    evaluate_operator_backtest,
)
from .territory.contracts import SiteLocation
from .territory.locations import replay_location
from .territory.pipeline import resolve_site_operator
from .territory.registry import parse_mastr_operator_registry, select_registry_as_known
from .territory.reports import render_resolution_markdown
from .territory.sources import ingest_territory_geojson, load_territory_release


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="capacity-backtest")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    sources = commands.add_parser("sources")
    source_commands = sources.add_subparsers(dest="source_command", required=True)
    source_commands.add_parser("list")
    fetch = source_commands.add_parser("fetch")
    fetch.add_argument("source_ids", nargs="*")
    verify = source_commands.add_parser("verify")
    verify.add_argument("manifests", nargs="+", type=Path)
    commands.add_parser("audit")
    commands.add_parser("backtest")
    capacity = commands.add_parser("capacity")
    capacity_commands = capacity.add_subparsers(dest="capacity_command", required=True)
    capacity_run = capacity_commands.add_parser("run")
    capacity_run.add_argument("--study", type=Path, required=True)
    live = commands.add_parser("live")
    live_commands = live.add_subparsers(dest="live_command", required=True)
    live_fetch = live_commands.add_parser("fetch")
    live_fetch.add_argument("--start-year", type=int, default=2021)
    live_fetch.add_argument("--end-year", type=int, default=2026)
    live_fetch.add_argument("--document-type", choices=("A65", "A75"), default="A65")
    live_fetch.add_argument("--monthly", action="store_true")
    live_run = live_commands.add_parser("backtest")
    live_run.add_argument("--held-out-year", type=int, default=2025)
    live_run.add_argument("--tabpfn", action="store_true")
    storage = commands.add_parser("storage")
    storage.add_argument(
        "storage_command",
        choices=(
            "init",
            "show",
            "verify",
            "inventory",
            "migrate-legacy",
            "compact-legacy-cloud",
        ),
    )
    storage.add_argument("--require-cloud", action="store_true")
    graph = commands.add_parser("graph")
    graph.add_argument("graph_command", choices=("export",))
    network = commands.add_parser("network")
    network.add_argument("network_command", choices=("validate", "inspect-cgmes"))
    network.add_argument("package", type=Path)
    gridcare = commands.add_parser("gridcare")
    gridcare.add_argument("gridcare_command", choices=("output",))
    operator = commands.add_parser("operator")
    operator_commands = operator.add_subparsers(dest="operator_command", required=True)
    validate_intake = operator_commands.add_parser("validate-intake")
    validate_intake.add_argument("manifest", type=Path)
    reconcile = operator_commands.add_parser("reconcile")
    reconcile.add_argument("predictions", type=Path)
    reconcile.add_argument("outcomes", type=Path)
    synthetic = commands.add_parser("synthetic")
    synthetic_commands = synthetic.add_subparsers(dest="synthetic_command", required=True)
    operator_package = synthetic_commands.add_parser("operator-package")
    operator_package.add_argument("--hours", type=int, default=8760)
    operator_package.add_argument("--requests-per-node", type=int, default=4)
    verify_operator = synthetic_commands.add_parser("verify-operator-package")
    verify_operator.add_argument("manifest", type=Path)
    queue_backtest = synthetic_commands.add_parser("queue-backtest")
    queue_backtest.add_argument("manifest", type=Path)
    synthetic_commands.add_parser("contingency-audit")
    hourly_ac = synthetic_commands.add_parser("hourly-ac")
    hourly_ac.add_argument("manifest", type=Path)
    optimized_deflex = synthetic_commands.add_parser("optimized-deflex")
    optimized_deflex.add_argument("--hours", type=int, default=168)
    weather = commands.add_parser("weather")
    weather.add_argument("weather_command", choices=("fetch",))
    weather.add_argument("--start-year", type=int, default=2021)
    weather.add_argument("--end-year", type=int, default=2025)
    regional = commands.add_parser("regional")
    regional_commands = regional.add_subparsers(dest="regional_command", required=True)
    regional_commands.add_parser("list")
    regional_commands.add_parser("verify")
    history = regional_commands.add_parser("history")
    history.add_argument("--start-date", type=date.fromisoformat, required=True)
    history.add_argument("--end-date", type=date.fromisoformat, required=True)
    history.add_argument("--delay-seconds", type=float, default=0.25)
    history.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    history.add_argument("--resume", action="store_true")
    history.add_argument("--revision-days-only", action="store_true")
    history_csv = regional_commands.add_parser("history-csv")
    history_csv.add_argument("--start-date", type=date.fromisoformat, required=True)
    history_csv.add_argument("--end-date", type=date.fromisoformat, required=True)
    regional_commands.add_parser("outages")
    regional_commands.add_parser("vertical-load")
    event_probe = regional_commands.add_parser("entsoe-events")
    event_probe.add_argument("--start-date", type=date.fromisoformat, required=True)
    event_probe.add_argument("--end-date", type=date.fromisoformat, required=True)
    dataset = regional_commands.add_parser("dataset")
    dataset.add_argument("--horizon-hours", type=int, choices=(1, 6, 24, 48), default=24)
    model = regional_commands.add_parser("model")
    model.add_argument("--horizon-hours", type=int, choices=(1, 6, 24, 48), default=24)
    regional_capture = regional_commands.add_parser("capture")
    regional_capture.add_argument("source_ids", nargs="*")
    territory = commands.add_parser("territory")
    territory_commands = territory.add_subparsers(dest="territory_command", required=True)
    validate_location = territory_commands.add_parser("validate-location")
    validate_location.add_argument("capture", type=Path)
    ingest_territory = territory_commands.add_parser("ingest-geojson")
    ingest_territory.add_argument("source", type=Path)
    ingest_territory.add_argument("output", type=Path)
    ingest_territory.add_argument("--source-id", required=True)
    ingest_territory.add_argument("--source-url", required=True)
    ingest_territory.add_argument("--licence", required=True)
    ingest_territory.add_argument("--retrieved-at", required=True)
    resolve_territory = territory_commands.add_parser("resolve")
    resolve_territory.add_argument("location", type=Path)
    resolve_territory.add_argument("territory_release", type=Path)
    resolve_territory.add_argument("registry_xml", type=Path)
    resolve_territory.add_argument("--decision-time", required=True)
    resolve_territory.add_argument("--evidence-cutoff", required=True)
    resolve_territory.add_argument("--registry-published-at", required=True)
    resolve_territory.add_argument("--registry-retrieved-at", required=True)
    resolve_territory.add_argument("--requested-mw", type=float, required=True)
    resolve_territory.add_argument("--output", type=Path)
    territory_backtest = territory_commands.add_parser("backtest")
    territory_backtest.add_argument("cases", type=Path)
    territory_backtest.add_argument("predictions", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_dir = args.root / "config" / "sources"
    layout = resolve_storage(args.root)
    if args.command == "capacity":
        run, destination = run_capacity_study(args.study, layout)
        print(
            json.dumps(
                {
                    "run_id": run.run_id,
                    "truth_class": run.truth_class,
                    "capacity_claim": run.capacity_claim,
                    "firm_screening_capacity_mw": run.statistics.firm_capacity_mw,
                    "p10_mw": run.statistics.p10_mw,
                    "p50_mw": run.statistics.p50_mw,
                    "p90_mw": run.statistics.p90_mw,
                    "input_fingerprint": run.input_fingerprint,
                    "report_subject_pcc_id": run.report_subject_pcc_id,
                    "operator_selected_pcc_id": run.operator_selected_pcc_id,
                    "pcc_results": [
                        {
                            "pcc_id": item.pcc.pcc_id,
                            "capacity_result_id": item.capacity_result.result_id,
                            "flexibility_requirement_id": (
                                item.flexibility_requirement.requirement_id
                            ),
                            "firm_screening_capacity_mw": item.statistics.firm_capacity_mw,
                            "conditional_screening_capacity_mw": (
                                item.flexibility_requirement.conditional_limit_mw
                            ),
                            "required_reduction_mw": (
                                item.flexibility_requirement.required_reduction_mw
                            ),
                        }
                        for item in run.pcc_results
                    ],
                    "output": str(destination),
                },
                indent=2,
            )
        )
        return 0
    if args.command == "territory":
        if args.territory_command == "validate-location":
            print(json.dumps(replay_location(args.capture).as_dict(), indent=2))
            return 0
        if args.territory_command == "ingest-geojson":
            rows = ingest_territory_geojson(
                args.source.read_bytes(), args.output, source_id=args.source_id,
                source_url=args.source_url, licence=args.licence, retrieved_at=args.retrieved_at,
            )
            print(json.dumps({"territory_count": len(rows), "output": str(args.output)}, indent=2))
            return 0
        if args.territory_command == "resolve":
            release = parse_mastr_operator_registry(
                args.registry_xml.read_bytes(), source_id="bnetza-mastr-operator-registry",
                published_at=args.registry_published_at, retrieved_at=args.registry_retrieved_at,
            )
            entries = select_registry_as_known(release, args.evidence_cutoff)
            result = resolve_site_operator(
                replay_location(args.location), load_territory_release(args.territory_release), entries,
                decision_time=args.decision_time, evidence_cutoff=args.evidence_cutoff,
                requested_mw=args.requested_mw,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                args.output.with_suffix(".md").write_text(render_resolution_markdown(result), encoding="utf-8")
            print(json.dumps(result, indent=2))
            return 0
        case_rows = json.loads(args.cases.read_text(encoding="utf-8"))
        prediction_rows = json.loads(args.predictions.read_text(encoding="utf-8"))
        cases = [HistoricalOperatorCase(**{**row, "site_location": SiteLocation(**row["site_location"])}) for row in case_rows]
        predictions = [OperatorPrediction(**{**row, "evidence_timestamps": tuple(row["evidence_timestamps"])}) for row in prediction_rows]
        print(json.dumps(evaluate_operator_backtest(cases, predictions), indent=2))
        return 0
    if args.command == "operator":
        if args.operator_command == "validate-intake":
            print(json.dumps(validate_operator_intake(args.manifest, args.root), indent=2))
            return 0
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        outcomes = json.loads(args.outcomes.read_text(encoding="utf-8"))
        print(json.dumps(reconcile_connection_outcomes(predictions, outcomes), indent=2))
        return 0
    if args.command == "synthetic":
        initialise_storage(layout, require_cloud=True)
        if args.synthetic_command == "verify-operator-package":
            print(
                json.dumps(
                    verify_synthetic_operator_package(args.manifest, layout.data_root), indent=2
                )
            )
            return 0
        if args.synthetic_command == "queue-backtest":
            rows = build_queue_feature_rows(args.manifest, layout.data_root)
            result = run_queue_backtest(rows)
            paths = write_queue_artifacts(rows, result, layout.data_root, args.manifest.parent.name)
            print(json.dumps({**result, "paths": paths}, indent=2))
            return 0
        if args.synthetic_command == "contingency-audit":
            study = load_study(args.root / "config" / "studies" / "berlin_capacity_backtest.yaml")
            result = run_contingency_v4_audit(study["scenarios"])
            path = (
                layout.data_root
                / "quality"
                / "contingency-selector-audit-v4"
                / "fixed-injection-50mw.json"
            )
            write_contingency_audit(result, path)
            print(json.dumps({**result, "rows": f"stored in {path}"}, indent=2))
            return 0
        if args.synthetic_command == "hourly-ac":
            result = run_representative_hourly_ac(args.manifest, layout.data_root)
            paths = write_hourly_ac(result, layout.data_root, args.manifest.parent.name)
            print(
                json.dumps(
                    {**result, "rows": f"stored in {paths['rows']}", "paths": paths}, indent=2
                )
            )
            return 0
        if args.synthetic_command == "optimized-deflex":
            records = benchmark_records_from_report(args.root / "reports" / "backtest-results.json")
            result = run_optimized_deflex_benchmark(records, hours=args.hours)
            paths = write_optimized_deflex(result, layout.data_root, f"hours-{args.hours}")
            print(
                json.dumps(
                    {**result, "results": f"stored in {paths['results']}", "paths": paths}, indent=2
                )
            )
            return 0
        records = benchmark_records_from_report(args.root / "reports" / "backtest-results.json")
        result = build_synthetic_operator_package(
            records,
            layout.data_root,
            layout.work_root,
            SyntheticOperatorConfig(
                hours=args.hours,
                requests_per_node=args.requests_per_node,
            ),
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "network":
        if args.network_command == "inspect-cgmes":
            inspection = inspect_cgmes_package(args.package)
            print(json.dumps(inspection.__dict__, indent=2))
            return 0
        package = load_network_package(args.package)
        print(
            json.dumps(
                {
                    "status": "validated",
                    "model_id": package.model_id,
                    "truth_class": package.truth_class.value,
                    "fingerprint": package.fingerprint(),
                    "available_capacity_mw": None,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "gridcare":
        print(json.dumps(unavailable_gridcare_output().as_dict(), indent=2))
        return 0
    if args.command == "regional":
        if args.regional_command == "list":
            print("\n".join(sorted(PUBLIC_ENDPOINTS)))
            return 0
        if args.regional_command == "verify":
            result = verify_regional_manifests(layout.data_root)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "verified" else 2
        if args.regional_command == "history":
            if args.end_date < args.start_date:
                raise SystemExit("end date must not precede start date")
            initialise_storage(layout, require_cloud=True)
            eligible: set[date] | None = None
            if args.revision_days_only:
                captures = captured_blobs(
                    layout.data_root, "fifty_hertz_redispatch_history_latest_csv"
                )
                if not captures:
                    raise SystemExit(
                        "capture the 50Hertz latest CSV before selecting revision days"
                    )
                latest_records = parse_history_csv(captures[-1][0].read_bytes())
                eligible = {
                    item.interval_start.astimezone(ZoneInfo("Europe/Berlin")).date()
                    for item in latest_records
                    if item.revision > 1
                }
            days = []
            eligible_count = 0
            current = args.start_date
            while current <= args.end_date:
                if eligible is not None and current not in eligible:
                    current += timedelta(days=1)
                    continue
                eligible_count += 1
                quality = (
                    layout.data_root
                    / "quality"
                    / "fifty_hertz_redispatch_history"
                    / f"{current.isoformat()}.json"
                )
                if not (args.resume and quality.exists()):
                    days.append(current)
                current += timedelta(days=1)
            results = capture_history_dates(
                days,
                layout.data_root,
                delay_seconds=args.delay_seconds,
                workers=args.workers,
            )
            summary = {
                "schema_version": "fifty-hertz-history-run-v1",
                "requested_start": args.start_date.isoformat(),
                "requested_end": args.end_date.isoformat(),
                "attempted": len(days),
                "eligible_dates": eligible_count,
                "skipped_existing": eligible_count - len(days),
                "captured": sum(item["status"] == "captured" for item in results),
                "failed": sum(item["status"] == "failed" for item in results),
                "records": sum(int(item.get("records", 0)) for item in results),
                "results": results,
            }
            run_path = (
                layout.data_root
                / "quality"
                / "fifty_hertz_redispatch_history"
                / "runs"
                / f"{args.start_date.isoformat()}_{args.end_date.isoformat()}.json"
            )
            atomic_write(run_path, (json.dumps(summary, indent=2) + "\n").encode())
            print(json.dumps({**summary, "results": f"{len(results)} date results"}, indent=2))
            return 0 if not summary["failed"] else 2
        if args.regional_command == "history-csv":
            if args.end_date < args.start_date:
                raise SystemExit("end date must not precede start date")
            initialise_storage(layout, require_cloud=True)
            result = capture_history_csv(args.start_date, args.end_date, layout.data_root)
            print(json.dumps(result, indent=2))
            return 0
        if args.regional_command == "outages":
            initialise_storage(layout, require_cloud=True)
            print(json.dumps(capture_outage_rss(layout.data_root), indent=2))
            return 0
        if args.regional_command == "entsoe-events":
            if args.end_date <= args.start_date:
                raise SystemExit("end date must be after start date")
            initialise_storage(layout, require_cloud=True)
            start = datetime.combine(args.start_date, datetime.min.time(), timezone.utc)
            end = datetime.combine(args.end_date, datetime.min.time(), timezone.utc)
            result = {
                "a78": capture_a78_probe(start, end, layout.data_root),
                "a63": capture_a63_probe(start, end, layout.data_root),
            }
            print(json.dumps(result, indent=2))
            return 0
        if args.regional_command == "vertical-load":
            initialise_storage(layout, require_cloud=True)
            print(json.dumps(capture_vertical_load_archive(layout.data_root), indent=2))
            return 0
        if args.regional_command == "dataset":
            initialise_storage(layout, require_cloud=True)
            print(
                json.dumps(
                    build_constraint_dataset(layout.data_root, horizon_hours=args.horizon_hours),
                    indent=2,
                )
            )
            return 0
        if args.regional_command == "model":
            candidates = []
            for path in (layout.data_root / "features" / "50hertz-constraint-hourly-v1").glob(
                "*/rows.jsonl"
            ):
                quality = json.loads((path.parent / "quality.json").read_text(encoding="utf-8"))
                if quality.get("horizon_hours") == args.horizon_hours:
                    candidates.append(path)
            if not candidates:
                raise SystemExit("build the 50Hertz constraint dataset first")
            result = run_constraint_models(
                max(candidates, key=lambda path: path.stat().st_mtime), layout.data_root
            )
            print(json.dumps({**result, "report": "stored in metrics artifact"}, indent=2))
            return 0
        initialise_storage(layout, require_cloud=True)
        selected = args.source_ids or list(PUBLIC_ENDPOINTS)
        unknown = sorted(set(selected) - set(PUBLIC_ENDPOINTS))
        if unknown:
            raise SystemExit(f"Unknown regional source ids: {', '.join(unknown)}")
        results = {}
        for source_id in selected:
            endpoint = PUBLIC_ENDPOINTS[source_id]
            captured = capture_endpoint(endpoint, layout.data_root, layout.work_root)
            item = {
                "status": captured.status.value,
                "bytes": captured.byte_length,
                "sha256": captured.sha256,
                "artifact": str(captured.artifact_path) if captured.artifact_path else None,
                "error": captured.error,
            }
            if source_id == "edis_completed_rss" and captured.artifact_path:
                records = parse_edis_rss(captured.artifact_path.read_bytes())
                report = profile_records(endpoint, records, snapshot_hash=captured.sha256 or "")
                quality_path = layout.data_root / "quality" / source_id / f"{captured.sha256}.json"
                write_quality_report(report, quality_path)
                item["quality_report"] = str(quality_path)
                item["records"] = len(records)
            elif (
                source_id == "netztransparenz_redispatch_archive_2013_2020"
                and captured.artifact_path
            ):
                report = profile_netztransparenz_archive(
                    captured.artifact_path.read_bytes(), snapshot_hash=captured.sha256 or ""
                )
                quality_path = layout.data_root / "quality" / source_id / f"{captured.sha256}.json"
                write_quality_report(report, quality_path)
                item["quality_report"] = str(quality_path)
                item["records"] = report["record_count"]
            elif source_id == "fifty_hertz_measures_rss" and captured.artifact_path:
                records = parse_generic_rss(captured.artifact_path.read_bytes())
                measures = normalize_measures(records)
                report = measure_quality(measures, snapshot_hash=captured.sha256 or "")
                quality_path = layout.data_root / "quality" / source_id / f"{captured.sha256}.json"
                write_quality_report(report, quality_path)
                normalized_path = (
                    layout.data_root
                    / "normalized"
                    / "grid-events-v1"
                    / source_id
                    / f"{captured.sha256}.jsonl"
                )
                atomic_write(
                    normalized_path,
                    (
                        "\n".join(
                            json.dumps(measure.as_dict(), ensure_ascii=False)
                            for measure in measures
                        )
                        + "\n"
                    ).encode(),
                )
                item["quality_report"] = str(quality_path)
                item["records"] = len(records)
                item["normalized"] = str(normalized_path)
            elif (
                source_id
                in {
                    "stromnetz_berlin_peak_load_history",
                    "stromnetz_berlin_hv_peak_load_history",
                }
                and captured.artifact_path
            ):
                report = profile_berlin_load_workbook(
                    captured.artifact_path.read_bytes(),
                    source_id=source_id,
                    snapshot_hash=captured.sha256 or "",
                )
                quality_path = layout.data_root / "quality" / source_id / f"{captured.sha256}.json"
                write_quality_report(report, quality_path)
                item["quality_report"] = str(quality_path)
                item["records"] = report["total_points"]
            elif (
                source_id
                in {
                    "wesernetz_bremen_upstream_load_2025",
                    "wesernetz_bremerhaven_upstream_load_2025",
                }
                and captured.artifact_path
            ):
                report = profile_wesernetz_load_csv(
                    captured.artifact_path.read_bytes(),
                    source_id=source_id,
                    snapshot_hash=captured.sha256 or "",
                )
                quality_path = layout.data_root / "quality" / source_id / f"{captured.sha256}.json"
                write_quality_report(report, quality_path)
                item["quality_report"] = str(quality_path)
                item["records"] = report["record_count"]
            elif captured.artifact_path:
                report = profile_artifact(
                    endpoint,
                    captured.artifact_path.read_bytes(),
                    snapshot_hash=captured.sha256 or "",
                )
                quality_path = layout.data_root / "quality" / source_id / f"{captured.sha256}.json"
                write_quality_report(report, quality_path)
                item["quality_report"] = str(quality_path)
            results[source_id] = item
        run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_report = (
            layout.data_root / "quality" / "runs" / f"regional-capture-{run_timestamp}.json"
        )
        atomic_write(
            run_report,
            (
                json.dumps(
                    {
                        "schema_version": "regional-capture-run-v1",
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "results": results,
                        "absence_is_zero": False,
                        "capacity_claim": False,
                    },
                    indent=2,
                )
                + "\n"
            ).encode(),
        )
        print(json.dumps(results, indent=2))
        return 0 if all(item["status"].startswith("success") for item in results.values()) else 2
    if args.command == "live":
        initialise_storage(layout)
        if args.live_command == "fetch":
            artifacts = []
            for year in range(args.start_year, args.end_year):
                periods = [
                    (
                        datetime(year, 1, 1, tzinfo=timezone.utc),
                        datetime(year + 1, 1, 1, tzinfo=timezone.utc),
                    )
                ]
                if args.monthly:
                    periods = []
                    for month in range(1, 13):
                        start = datetime(year, month, 1, tzinfo=timezone.utc)
                        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
                        periods.append((start, end))
                for start, end in periods:
                    artifacts.append(
                        str(
                            fetch_document(
                                args.document_type,
                                start,
                                end,
                                layout.data_root,
                            )
                        )
                    )
            print(json.dumps({"status": "succeeded", "artifacts": artifacts}, indent=2))
            return 0
        report = run_live_backtest(args.root, args.held_out_year, include_tabpfn=args.tabpfn)
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "storage":
        if args.storage_command == "init":
            initialise_storage(layout, require_cloud=args.require_cloud)
            result = layout.as_dict()
        elif args.storage_command == "verify":
            result = storage_health(layout, require_cloud=args.require_cloud)
        elif args.storage_command == "inventory":
            result = storage_inventory(layout)
        elif args.storage_command == "migrate-legacy":
            result = migrate_legacy_data(layout)
            destination = layout.data_root / "manifests" / "migrations" / "legacy-migration-v1.json"
            atomic_write(destination, (json.dumps(result, indent=2) + "\n").encode())
        elif args.storage_command == "compact-legacy-cloud":
            result = compact_legacy_cloud_snapshots(layout)
            destination = (
                layout.data_root / "manifests" / "migrations" / "cloud-v1-compaction-v1.json"
            )
            atomic_write(destination, (json.dumps(result, indent=2) + "\n").encode())
        else:
            result = layout.as_dict()
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "weather":
        profiles = fetch_weather(layout.data_root, args.start_year, args.end_year)
        print(json.dumps([profile.__dict__ for profile in profiles], indent=2))
        return 0 if all(profile.accepted for profile in profiles) else 2
    if args.command == "graph":
        initialise_storage(layout)
        destination = layout.data_root / "exports" / "neo4j" / "berlin-synthetic"
        result = export_neo4j_csv(build_berlin_synthetic_model(), destination)
        print(json.dumps({**result, "output": str(destination)}, indent=2))
        return 0
    if args.command == "backtest":
        result = run_and_write(
            args.root / "config/studies/berlin_capacity_backtest.yaml",
            args.root / "reports",
        )
        metrics = result["metrics"]
        report = args.root / "reports/backtest-report.md"
        report.write_text(
            "# Grid-capacity backtest report\n\n"
            "## Outcome\n\n"
            f"- Ranking release gate: **{'PASS' if metrics['ranking_gate_passed'] else 'FAIL'}**\n"
            f"- Capacity-band release gate: **{'PASS' if metrics['capacity_gate_passed'] else 'FAIL'}**\n"
            "- Berlin available capacity: **Unknown - operator evidence required**\n\n"
            "## Validation metrics\n\n"
            f"- Evaluated cases: {metrics['evaluated_count']}\n"
            f"- Unique candidate nodes: {metrics['unique_candidate_count']}\n"
            f"- Held-out network families: {metrics['network_family_count']}\n"
            f"- Mean absolute error: {metrics['mean_absolute_error_mw']} MW\n"
            f"- Median absolute error: {metrics['median_absolute_error_mw']} MW\n"
            f"- Overstatement rate: {metrics['overstatement_rate']:.1%}\n"
            f"- Severe overstatement rate: {metrics['severe_overstatement_rate']:.1%}\n"
            f"- Interval coverage: {metrics['interval_coverage']:.1%}\n"
            f"- Top-10 recall: {metrics['top_10_recall']:.1%}\n\n"
            f"- Contingency-selector recall: {metrics['contingency_selector_recall']:.1%}\n"
            f"- Exhaustive contingency audit cases: {metrics['contingency_selector_audit_count']}\n"
            f"- Graph contingency reduction: {metrics['mean_contingency_reduction_ratio']:.1%}\n"
            f"- Topology provider: {metrics['topology_provider']}\n\n"
            "## Interpretation\n\n"
            "The benchmark uses real public Berlin map anchors with synthetic electrical parameters. "
            "It validates calculation mechanics only; it is not a model of live Berlin capacity. "
            f"{metrics['network_family_count']} deliberately distinct synthetic network families "
            "are evaluated with each target "
            "family held out from calibration. Exhaustive N-1 physics audits a stratified subset; "
            "graph selection is measured there and never calculates MW. Ranking and "
            "capacity bands remain blocked unless every safety gate passes.\n",
            encoding="utf-8",
        )
        print("Wrote reports/backtest-results.json and reports/backtest-report.md")
        return 0
    if args.command == "audit":
        write_audit(
            config_dir,
            args.root / "reports/evidence-audit.json",
            args.root / "reports/evidence-audit.md",
        )
        print("Wrote reports/evidence-audit.json and reports/evidence-audit.md")
        return 0
    if args.source_command == "list":
        for source in load_registry(config_dir):
            print(f"{source.id}\t{source.truth_class.value}\t{source.url}")
        return 0
    if args.source_command == "verify":
        valid = all(verify_snapshot(path) for path in args.manifests)
        print("verified" if valid else "verification failed")
        return 0 if valid else 1
    registry = registry_by_id(config_dir)
    selected = args.source_ids or list(registry)
    unknown = sorted(set(selected) - set(registry))
    if unknown:
        raise SystemExit(f"Unknown source ids: {', '.join(unknown)}")
    results = {}
    for source_id in selected:
        result = fetch_source(registry[source_id], layout.data_root / "raw")
        results[source_id] = {"status": result.status, "error": result.error}
    print(json.dumps(results, indent=2))
    success = all(item["status"] in {"succeeded", "disabled"} for item in results.values())
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
