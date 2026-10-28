from capacity_backtest.application import ROLLING_PLAN_REQUEST_SCHEMA, run_rolling_facility_plan

from .test_application_facility import request as facility_request


def request() -> dict[str, object]:
    plan = facility_request()
    size = len(plan["intervals"])
    scenario = {
        "scenario_id": "declared-base",
        "probability": 1,
        "battery_temperature_c": [20.0] * size,
        "onsite_generation_mw": [0.0] * size,
        "assumption_ids": ["customer:forecast"],
    }
    return {
        "schema_version": ROLLING_PLAN_REQUEST_SCHEMA,
        "facility_plan": plan,
        "windows": [
            {
                "window_id": "w1",
                "cutoff": "2025-12-31T00:00:00+00:00",
                "forecast_fingerprint": "a" * 64,
                "scenarios": [scenario],
                "recalculation_reason": "initial",
            },
            {
                "window_id": "w2",
                "cutoff": "2025-12-31T01:00:00+00:00",
                "forecast_fingerprint": "b" * 64,
                "scenarios": [scenario],
                "recalculation_reason": "forecast_revision",
            },
        ],
        "confidence": 0.9,
    }


def test_rolling_boundary_preserves_cutoffs_fallbacks_and_non_dispatch() -> None:
    first = run_rolling_facility_plan(request())
    second = run_rolling_facility_plan(request())
    assert first == second
    assert len(first["result"]["windows"]) == 2
    assert first["result"]["accepted_revisions"] == 1
    assert first["capacity_claim"] is False
    assert first["automatic_live_dispatch_authorized"] is False
