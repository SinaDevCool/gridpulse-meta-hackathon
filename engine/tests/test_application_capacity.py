from dataclasses import asdict

from capacity_backtest.application import (
    CAPACITY_REQUIREMENT_REQUEST_SCHEMA,
    run_capacity_requirement,
)

from .test_flexibility_requirement import capacity_result


def test_capacity_application_preserves_provenance_and_unknown_terms() -> None:
    capacity = capacity_result()
    request = {
        "schema_version": CAPACITY_REQUIREMENT_REQUEST_SCHEMA,
        "capacity_result": asdict(capacity),
        "site_id": "site",
        "pcc_id": "pcc",
        "requested_import_mw": 90,
        "expected_provenance_fingerprint": capacity.provenance.fingerprint(),
    }
    result = run_capacity_requirement(request)
    requirement = result["requirement"]
    assert requirement["required_reduction_mw"] == 10
    assert "response_time_unknown" in requirement["blockers"]
    assert result["capacity_claim"] is False
    assert len(result["result_fingerprint"]) == 64
