"""Offline measurement-to-review pipeline over existing adapters and fit gates.

No automatic activation, new database, network download or serving-time training.
"""
from dataclasses import asdict
from pathlib import Path

from capacity_backtest.adapters.workload import parse_workload_executions
from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.artifacts import chronological_dataset_manifest, write_artifact
from capacity_backtest.data_center.profile_calibration import calibrate_power_profile
from capacity_backtest.domain.base import parse_aware_timestamp


def prepare_workload_calibration(content: bytes, *, dataset_id: str, source: str, license: str,
                                 evidence_cutoff: str, train_end: str, validation_end: str,
                                 truth_class: str, workload_id: str) -> dict:
    if len(content) > 16 * 1024 * 1024:
        raise ValueError("offline capture exceeds size budget")
    executions = parse_workload_executions(content, source_id=source)
    cutoff = parse_aware_timestamp(evidence_cutoff, "evidence cutoff")
    if any(row.available_at is None or parse_aware_timestamp(row.available_at, "available_at") > cutoff for row in executions):
        raise ValueError("each execution requires cutoff-safe availability provenance")
    manifest = chronological_dataset_manifest(dataset_id=dataset_id, source=source, license=license,
        content=content, execution_windows=tuple((e.execution_id, e.started_at, e.ended_at) for e in executions),
        evidence_cutoff=evidence_cutoff, train_end=train_end, validation_end=validation_end,
        unit_boundaries={"measured_power_mw": "GPU interval-average MW", "work": "reference work duration minutes"},
        transformation_version="workload-review-pipeline-v1", truth_class=truth_class)
    if any(e.workload_id != workload_id for e in executions):
        raise ValueError("one workload/configuration calibration per candidate is required")
    train = tuple(e for e in executions if e.execution_id in manifest.train_ids)
    validation = tuple(e for e in executions if e.execution_id in manifest.validation_ids)
    test = tuple(e for e in executions if e.execution_id in manifest.test_ids)
    # Both evaluations fit only the training executions. Test data never fits parameters.
    val = calibrate_power_profile(workload_id, train + validation,
        holdout_execution_ids=manifest.validation_ids, truth_class=TruthClass(truth_class))
    heldout = calibrate_power_profile(workload_id, train + test,
        holdout_execution_ids=manifest.test_ids, truth_class=TruthClass(truth_class))
    if val.profile != heldout.profile:
        raise ValueError("held-out evaluation unexpectedly changed fitted parameters")
    return {"schema_version": "gridpulse-workload-calibration-review-v1", "dataset": asdict(manifest),
            "validation": asdict(val), "test": asdict(heldout),
            "ready_for_human_review": val.accepted and heldout.accepted and truth_class != "synthetic_demonstration",
            "activated": False, "automatic_live_dispatch_authorized": False,
            "limitations": ["GPU measurement boundary only; not facility energy or cooling calibration.",
                            "Existing model artifact qualification and reviewer approval remain required."]}


def main() -> None:
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("metadata", type=Path, help="JSON keyword arguments for prepare_workload_calibration")
    parser.add_argument("output", type=Path, help="Immutable candidate artifact directory")
    args = parser.parse_args()
    if args.capture.stat().st_size > 16 * 1024 * 1024 or args.metadata.stat().st_size > 65536:
        raise ValueError("offline input exceeds size budget")
    candidate = prepare_workload_calibration(args.capture.read_bytes(), **json.loads(args.metadata.read_text(encoding="utf-8")))
    print(write_artifact(args.output, candidate))


if __name__ == "__main__":
    main()
