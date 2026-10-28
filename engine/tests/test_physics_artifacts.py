from dataclasses import replace

import pytest

from capacity_backtest.application.rolling import run_chronological_shadow
from capacity_backtest.data_center.artifacts import (
    DatasetManifest,
    chronological_dataset_manifest,
    read_artifact,
    write_artifact,
)

from .test_application_facility import request


def test_chronological_capture_refuses_crossing_or_future_execution():
    args = {"dataset_id": "trace", "source": "public-trace", "license": "declared-by-owner", "content": b"fixture",
                "execution_windows": tuple((str(i), f"2026-01-0{i}T00:00:00Z", f"2026-01-0{i}T01:00:00Z") for i in (1, 2, 3)),
                "evidence_cutoff": "2026-01-04T00:00:00Z", "train_end": "2026-01-02T00:00:00Z",
                "validation_end": "2026-01-03T00:00:00Z", "unit_boundaries": {"gpu_power": "MW"},
                "transformation_version": "normalized-v1", "truth_class": "synthetic_demonstration"}
    result = chronological_dataset_manifest(**args)
    assert result.train_ids == ("1",) and result.validation_ids == ("2",) and result.test_ids == ("3",)
    with pytest.raises(ValueError, match="crosses"):
        chronological_dataset_manifest(**{**args, "execution_windows": (*args["execution_windows"], ("cross", "2026-01-01T23:00:00Z", "2026-01-02T01:00:00Z"))})


def test_dataset_split_leakage_and_artifact_tampering(tmp_path):
    dataset = DatasetManifest("d", "fixture", "internal", "2026-01-01T00:00:00Z", "a" * 64,
                              {"power": "AC MW"}, "v1", ("train",), ("validation",), ("test",), "synthetic_demonstration")
    dataset.validate()
    with pytest.raises(ValueError, match="overlap"):
        replace(dataset, test_ids=("train",)).validate()
    identity = write_artifact(tmp_path, {"version": 1})
    assert read_artifact(tmp_path, identity) == {"version": 1}
    (tmp_path / (identity + ".json")).write_text('{"version": 2}')
    with pytest.raises(ValueError, match="integrity"):
        read_artifact(tmp_path, identity)


def test_chronological_shadow_carries_work_and_excludes_future_forecasts():
    plan = request()
    plan["policy"]["solver_time_limit_seconds"] = 5
    # Retain an event in each remaining horizon.
    plan["policy"]["event_intervals"] = [True] * len(plan["intervals"])
    plan["requirement"]["maximum_event_duration_minutes"] = None
    plan["requirement"]["conservative_required_reduction_mw"] = 0
    plan["requirement"]["required_reduction_mw"] = 0
    plan["requirement"]["requested_import_mw"] = plan["requirement"]["firm_limit_mw"]
    plan["requirement"]["surplus_capacity_mw"] = max(0, plan["requirement"]["conditional_limit_mw"] - plan["requirement"]["requested_import_mw"])
    payload = {"schema_version": "gridpulse-chronological-shadow-request-v1", "facility_plan": plan,
               "windows": [{"cutoff": i["start"], "available_at": i["start"], "changes": []} for i in plan["intervals"][:2]]}
    result = run_chronological_shadow(payload)
    assert len(result["revisions"]) == 2
    assert result["state_source"] == "model_replay_not_measured"
    assert not result["automatic_live_dispatch_authorized"]
    payload["windows"][0]["available_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="future"):
        run_chronological_shadow(payload)


def test_release_identity_detects_different_wheel_bytes(tmp_path):
    from capacity_backtest.data_center.artifacts import release_manifest, verify_release_manifest
    wheel, lock = tmp_path / "engine.whl", tmp_path / "requirements.lock"
    wheel.write_bytes(b"candidate")
    lock.write_text("scipy==1.14.1", encoding="utf-8")
    args = {"wheel": wheel, "dependency_lock": lock, "source_revision": "a" * 40, "engine_version": "test"}
    manifest = release_manifest(**args)
    verify_release_manifest(manifest, **args)
    wheel.write_bytes(b"different candidate")
    with pytest.raises(ValueError, match="mismatch"):
        verify_release_manifest(manifest, **args)


def test_shadow_carries_battery_boundary_and_remaining_work():
    from dataclasses import asdict

    from capacity_backtest.phase2.battery import BatteryConfig
    plan = request()
    plan["policy"]["solver_time_limit_seconds"] = 5
    plan["workloads"][0]["expected_duration_minutes"] = 180
    plan["batteries"] = [asdict(BatteryConfig("battery", .1, .2, .2, .02, .18))]
    plan["policy"]["event_intervals"] = [True] * len(plan["intervals"])
    plan["requirement"]["maximum_event_duration_minutes"] = None
    plan["requirement"]["conservative_required_reduction_mw"] = 0
    plan["requirement"]["required_reduction_mw"] = 0
    plan["requirement"]["requested_import_mw"] = plan["requirement"]["firm_limit_mw"]
    plan["requirement"]["surplus_capacity_mw"] = max(0, plan["requirement"]["conditional_limit_mw"] - plan["requirement"]["requested_import_mw"])
    result = run_chronological_shadow({"schema_version": "gridpulse-chronological-shadow-request-v1",
        "facility_plan": plan, "windows": [{"cutoff": i["start"], "available_at": i["start"]} for i in plan["intervals"][:2]]})
    first, second = result["revisions"]
    assert second["initial_state"]["batteries"][0]["initial_soc_mwh"] == pytest.approx(
        first["plan"]["result"]["battery_trajectories"][0]["points"][0]["soc_mwh"])
    prior_work = {t["workload_id"]: t for t in first["plan"]["result"]["portfolio"]["workload_trajectories"]}
    for job in second["initial_state"]["workloads"]:
        assert job["remaining_work_minutes"] == pytest.approx(prior_work[job["workload_id"]]["points"][0]["remaining_work_hours"] * 60)



def test_qualified_model_gate_checks_release_time_range_and_measured_evidence(tmp_path):
    from capacity_backtest.data_center.artifacts import (
        DatasetManifest,
        load_qualified_model,
        qualify_model_artifact,
        write_artifact,
    )
    dataset = DatasetManifest("site", "meter", "private-authorised", "2026-01-01T00:00:00Z", "a" * 64,
                              {"power": "MW"}, "v1", ("train",), ("validation",), ("test",), "measured")
    artifact = qualify_model_artifact(model_name="cooling", model_version="v1", parameters={"factor": .2},
        dataset=dataset, metrics={"error": .01}, thresholds={"error": .05}, operating_range={"load_mw": [1, 10]},
        reviewer="operator-review", approved_at="2026-01-02T00:00:00Z")
    fingerprint = write_artifact(tmp_path, artifact)
    args = {"release": {"schema_version": "gridpulse-engine-release-v1", "calibration_fingerprints": [fingerprint]},
                "model_name": "cooling", "observed_at": "2026-01-03T00:00:00Z", "operating_point": {"load_mw": 5}}
    loaded = load_qualified_model(tmp_path, fingerprint, **args)
    assert loaded["parameters"] == artifact["parameters"]
    assert loaded["dataset"]["test_ids"] == ["test"]
    for change in ({"operating_point": {"load_mw": 11}}, {"observed_at": "2026-01-01T00:00:00Z"},
                   {"release": {"calibration_fingerprints": []}}, {"operating_point": {}}):
        with pytest.raises(ValueError):
            load_qualified_model(tmp_path, fingerprint, **{**args, **change})


def test_shadow_rechecks_cumulative_fatigue_against_immutable_reference():
    plan = request()
    plan["policy"]["solver_time_limit_seconds"] = 5
    plan["fatigue_limits"] = {"maximum_consecutive_event_hours": 24, "maximum_event_hours_per_rolling_day": 24,
        "maximum_events_per_rolling_week": 100, "annual_shifted_energy_mwh": 1000,
        "annual_battery_cycles": 1000, "minimum_cooldown_hours": 0}
    result = run_chronological_shadow({"schema_version": "gridpulse-chronological-shadow-request-v1",
        "facility_plan": plan, "windows": [{"cutoff": p["start"], "available_at": p["start"]} for p in plan["intervals"][:2]]})
    assert all(r["accepted"] and r["cumulative_fatigue"]["passed"] for r in result["revisions"])
    first, last = result["revisions"]
    reference = first["plan"]["result"]["baseline_facility"]["points"]
    actual = first["plan"]["result"]["facility"]["points"][:1] + last["plan"]["result"]["facility"]["points"]
    expected = sum(max(0, b["grid_import_mw"] - a["grid_import_mw"]) for b, a in zip(reference, actual))
    assert last["cumulative_fatigue"]["shifted_energy_mwh"] == pytest.approx(expected)
