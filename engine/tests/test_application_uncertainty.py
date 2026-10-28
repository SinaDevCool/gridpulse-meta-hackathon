from capacity_backtest.application import UNCERTAINTY_REQUEST_SCHEMA, run_facility_uncertainty

from .test_application_facility import request as facility_request


def request() -> dict[str, object]:
    return {
        "schema_version": UNCERTAINTY_REQUEST_SCHEMA,
        "facility_plan": facility_request(),
        "bounds": {
            "temperature_min_c": 20.0,
            "temperature_max_c": 30.0,
            "onsite_generation_min_mw": 0.0,
            "onsite_generation_max_mw": 0.0,
        },
        "scenario_count": 3,
        "seed": 42,
        "risk_policy": "chance_constrained",
        "confidence": 0.9,
    }


def test_uncertainty_boundary_is_seeded_deterministic_and_non_operational() -> None:
    first = run_facility_uncertainty(request())
    second = run_facility_uncertainty(request())
    assert first == second
    assert len(first["result"]["outcomes"]) == 3
    assert first["capacity_claim"] is False
    assert first["automatic_live_dispatch_authorized"] is False
    assert len(first["result_fingerprint"]) == 64


def test_uncertainty_boundary_fails_closed_on_invalid_probability_inputs() -> None:
    payload = request()
    payload["scenario_count"] = 0
    try:
        run_facility_uncertainty(payload)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("invalid uncertainty request must fail closed")


def test_explicit_common_plan_boundary_retains_non_operational_provenance():
    payload = request()
    payload["facility_plan"]["policy"]["solver_time_limit_seconds"] = 5
    payload["evaluation_method"] = "common_command_scenario_milp"
    result = run_facility_uncertainty(payload)
    assert result["result"]["common_plan_validated"]
    assert result["result"]["evaluation_method"] == "common_command_scenario_milp"
    assert result["automatic_live_dispatch_authorized"] is False
