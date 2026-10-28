from capacity_backtest.application import contract_manifest


def test_contract_manifest_is_deterministic_and_complete() -> None:
    first = contract_manifest()
    second = contract_manifest()
    assert first == second
    assert len(first["fingerprint"]) == 64
    assert {item["operation"] for item in first["contracts"]} == {
        "capacity_requirement",
        "facility_plan", "facility_accounting",
        "facility_experiment", "chronological_shadow",
        "fca_interval",
        "market_qualification",
        "rolling_facility_plan",
        "facility_uncertainty",
        "facility_historical_replay",
        "operator_enquiry_package",
        "shadow_verification",
    }
    assert all(str(item["endpoint"]).startswith("/v1/jobs/") for item in first["contracts"])
