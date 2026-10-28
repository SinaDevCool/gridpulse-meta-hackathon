from capacity_backtest.application import (
    SHADOW_VERIFICATION_REQUEST_SCHEMA,
    run_shadow_verification,
)


def request() -> dict[str, object]:
    timestamp = "2026-01-01T00:00:00+00:00"
    return {
        "schema_version": SHADOW_VERIFICATION_REQUEST_SCHEMA,
        "facility_id": "facility-a",
        "generated_at": timestamp,
        "plan_fingerprint": "a" * 64,
        "planned_grid_import_mw": [10, 10, 10],
        "observed_grid_import_mw": [12, 12, 12],
        "uncertainty_band_mw": [0.2, 0.2, 0.2],
        "observations": [{
            "observation_id": "o-1", "measurement_id": "pcc-1", "component": "pcc",
            "event_at": timestamp, "available_at": timestamp, "ingested_at": timestamp,
            "sequence": 0, "value": 12, "unit": "MW", "quality": "valid",
            "source_id": "read-only-adapter", "evidence_sha256": "b" * 64,
        }],
        "reference_times": [timestamp],
        "supplied_energy_mwh": 3,
        "consumed_energy_mwh": 3,
        "required_reduction_mw": 2,
        "delivered_reduction_mw": 0,
        "security_controls": {
            "read_only_accounts": True, "network_segmented": True, "tls_enforced": True,
            "secrets_externalized": True, "secrets_rotated": True, "storage_encrypted": True,
            "audit_logging": True, "dependency_inventory": True, "vulnerability_process": True,
            "incident_response_tested": True, "backup_restore_tested": True,
            "adapter_allow_list": True, "tenant_data_pseudonymized": True,
        },
    }


def test_shadow_boundary_is_read_only_deterministic_and_fail_safe() -> None:
    first = run_shadow_verification(request())
    assert first == run_shadow_verification(request())
    assert first["read_only"] is True
    assert first["automatic_live_dispatch_authorized"] is False
    assert first["snapshot"]["divergence"]["classification"] == "safe_limit"
    assert "persistent_model_divergence" in first["blockers"]
