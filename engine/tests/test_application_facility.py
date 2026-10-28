from dataclasses import asdict

from capacity_backtest.application import FACILITY_PLAN_REQUEST_SCHEMA, run_facility_plan

from .test_data_center_optimizer import inputs


def request() -> dict[str, object]:
    values = inputs()
    portfolio = values["portfolio"]
    return {
        "schema_version": FACILITY_PLAN_REQUEST_SCHEMA,
        "portfolio_id": portfolio.portfolio_id,
        "requirement": asdict(values["requirement"]),
        "intervals": [asdict(item) for item in values["intervals"]],
        "facility": asdict(values["facility"]),
        "workloads": [asdict(item) for item in portfolio.workloads],
        "profiles": [asdict(item) for item in values["profiles"].values()],
        "policy": asdict(values["policy"]),
        "economics": asdict(values["economics"]),
        "cooling": asdict(values["cooling"]),
    }


def test_application_plan_is_deterministic_and_non_operational() -> None:
    first = run_facility_plan(request())
    second = run_facility_plan(request())
    assert first == second
    assert first["result"]["status"] == "optimal"
    assert len(first["input_fingerprint"]) == 64
    assert len(first["result_fingerprint"]) == 64
    assert first["capacity_claim"] is False
    assert first["automatic_live_dispatch_authorized"] is False


def test_application_boundary_rejects_unknown_schema() -> None:
    payload = request()
    payload["schema_version"] = "future"
    try:
        run_facility_plan(payload)
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unsupported transport contract must fail closed")


def test_physical_findings_are_plan_specific_not_causal_claims():
    result = run_facility_plan(request())
    evidence = result["diagnostic_evidence"]
    assert evidence["available"]
    assert evidence["causal_binding_constraints_assessed"] is False
    margin = next(f for f in evidence["findings"] if f["code"] == "peak_import_margin")
    assert margin["value"] == request()["facility"]["import_limit_mw"] - result["result"]["facility"]["maximum_grid_import_mw"]
