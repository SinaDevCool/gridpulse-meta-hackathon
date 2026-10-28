from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from capacity_backtest.capacity_study.runner import run_capacity_study
from capacity_backtest.storage import StorageLayout

ROOT = Path(__file__).parents[1]


def layout(tmp_path: Path) -> StorageLayout:
    cloud = tmp_path / "OneDrive"
    return StorageLayout(ROOT, cloud / "data", tmp_path / "work", "onedrive_filesystem", cloud)


def configuration(tmp_path: Path, *, pcc_count: int = 1) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((ROOT / "config/studies/capacity_screening_mock.yaml").read_text())
    config["maximum_pcc_candidates"] = pcc_count
    config["operating_states"]["hours"] = 2
    destination = tmp_path / "study.yaml"
    destination.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
    return destination


def test_runner_emits_capacity_requirement_and_hashed_artifacts(tmp_path: Path) -> None:
    run, destination = run_capacity_study(configuration(tmp_path), layout(tmp_path))
    payload = json.loads((destination / "capacity-study.json").read_text())
    manifest = json.loads((destination / "manifest.json").read_text())
    report = (destination / "capacity-study.md").read_text()
    assert payload["schema_version"] == "gridpulse-capacity-study-run-v2"
    assert len(payload["pcc_results"]) == 1
    result = run.pcc_results[0]
    assert result.flexibility_requirement.capacity_result_id == result.capacity_result.result_id
    assert result.flexibility_requirement.capacity_provenance_fingerprint == result.capacity_result.provenance.fingerprint()
    assert result.capacity_result.capacity_claim is False
    assert result.flexibility_requirement.operator_confirmed is False
    assert manifest["automatic_live_dispatch_authorized"] is False
    assert manifest["artifact_sha256"]["capacity-study.json"] == hashlib.sha256((destination / "capacity-study.json").read_bytes()).hexdigest()
    assert "Required reduction" in report
    assert "Operator-confirmed capacity claim: **No**" in report


def test_multi_pcc_results_are_isolated_and_never_operator_selected(tmp_path: Path) -> None:
    run, _ = run_capacity_study(configuration(tmp_path, pcc_count=2), layout(tmp_path))
    assert len(run.pcc_results) == 2
    assert len({item.pcc.pcc_id for item in run.pcc_results}) == 2
    assert all(item.realization_count == 1 for item in run.pcc_results)
    assert run.operator_selected_pcc_id is None
    assert all(item.flexibility_requirement.pcc_id == item.pcc.pcc_id for item in run.pcc_results)


def test_identical_fixed_inputs_produce_identical_ids_and_fingerprints(tmp_path: Path) -> None:
    config = configuration(tmp_path)
    first, first_destination = run_capacity_study(config, layout(tmp_path / "first"))
    second, second_destination = run_capacity_study(config, layout(tmp_path / "second"))
    assert first.run_id == second.run_id
    assert first.input_fingerprint == second.input_fingerprint
    assert first.pcc_results[0].capacity_result.result_id == second.pcc_results[0].capacity_result.result_id
    assert first.pcc_results[0].flexibility_requirement.requirement_id == second.pcc_results[0].flexibility_requirement.requirement_id
    first_manifest = json.loads((first_destination / "manifest.json").read_text())
    second_manifest = json.loads((second_destination / "manifest.json").read_text())
    assert first_manifest["pipeline_fingerprint"] == second_manifest["pipeline_fingerprint"]


def test_policy_change_changes_requirement_identity(tmp_path: Path) -> None:
    first_config = configuration(tmp_path / "a")
    second_config = configuration(tmp_path / "b")
    values = yaml.safe_load(second_config.read_text())
    values["planning"]["conditional_capacity"]["availability"] = 0.99
    second_config.write_text(yaml.safe_dump(values, sort_keys=True))
    first, _ = run_capacity_study(first_config, layout(tmp_path / "one"))
    second, _ = run_capacity_study(second_config, layout(tmp_path / "two"))
    assert first.pcc_results[0].flexibility_requirement.requirement_id != second.pcc_results[0].flexibility_requirement.requirement_id
