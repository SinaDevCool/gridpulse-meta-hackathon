from dataclasses import asdict

from capacity_backtest.application.facility import run_facility_plan
from capacity_backtest.phase2.battery import BatteryConfig

from .test_application_facility import request


def test_completed_compute_does_not_remove_battery_or_cooling_obligations():
    model = request()
    model["workloads"] = []
    model["profiles"] = []
    model["requirement"]["required_reduction_mw"] = 0
    model["requirement"]["conservative_required_reduction_mw"] = 0
    model["requirement"]["requested_import_mw"] = model["requirement"]["firm_limit_mw"]
    model["requirement"]["surplus_capacity_mw"] = max(0, model["requirement"]["conditional_limit_mw"] - model["requirement"]["requested_import_mw"])
    model["batteries"] = [asdict(BatteryConfig("battery", .1, .2, .1, .02, .15))]
    result = run_facility_plan(model)["result"]
    assert result["status"] in {"optimal", "feasible_not_proven_optimal"}
    assert not result["portfolio"]["workload_trajectories"]
    assert len(result["facility"]["points"]) == len(model["intervals"])
    assert result["battery_trajectories"][0]["points"][-1]["soc_mwh"] >= .15 - 1e-8
    from capacity_backtest.application.rolling import run_chronological_shadow
    model["policy"]["solver_time_limit_seconds"] = 5
    shadow = run_chronological_shadow({"schema_version": "gridpulse-chronological-shadow-request-v1",
        "facility_plan": model, "windows": [{"cutoff": item["start"], "available_at": item["start"]} for item in model["intervals"][:2]]})
    assert len(shadow["revisions"]) == 2
    assert all(item["remaining_battery_horizon_assessed"] for item in shadow["revisions"])
    assert shadow["revisions"][1]["initial_state"]["workloads"] == []
    assert shadow["revisions"][-1]["plan"]["result"]["battery_trajectories"][0]["points"][-1]["soc_mwh"] >= .15 - 1e-8
