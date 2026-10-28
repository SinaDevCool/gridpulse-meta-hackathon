from capacity_backtest.application import EVIDENCE_PACKAGE_REQUEST_SCHEMA, run_evidence_package


def test_evidence_boundary_is_deterministic_hashed_and_nonclaiming() -> None:
    request = {
        "schema_version": EVIDENCE_PACKAGE_REQUEST_SCHEMA,
        "package_id": "enquiry-1",
        "artifacts": {
            "capacity_requirement": {"fingerprint": "a" * 64},
            "facility_plan": {"fingerprint": "b" * 64},
        },
        "blockers": ["operator_confirmation_required"],
        "assumption_ids": ["assumption-1"],
    }
    first = run_evidence_package(request)
    assert first == run_evidence_package(request)
    assert first["package"]["manifest"]["package_fingerprint"] == first["package"]["package_fingerprint"]
    assert "Capacity claim: **No**" in first["package"]["markdown_text"]
    assert first["capacity_claim"] is False
