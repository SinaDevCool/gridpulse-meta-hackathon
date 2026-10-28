import hashlib
import json

import pytest

from capacity_backtest.operator_reconciliation import (
    reconcile_connection_outcomes,
    validate_operator_intake,
)


def test_operator_intake_is_external_and_hash_checked(tmp_path):
    confidential = tmp_path / "confidential"
    confidential.mkdir()
    data = confidential / "ratings.csv"
    data.write_text("asset,rating_mva\nA,100\n", encoding="utf-8")
    manifest = confidential / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "operator-intake-v1",
                "operator": "example",
                "dataset_id": "example-1",
                "retrieved_at": "2026-01-02T00:00:00Z",
                "effective_from": "2025-01-01T00:00:00Z",
                "geographic_resolution": "asset",
                "units": {"rating": "MVA"},
                "permitted_uses": ["validation"],
                "prohibited_uses": ["publication"],
                "files": [
                    {
                        "path": "ratings.csv",
                        "sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                        "content_type": "text/csv",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = validate_operator_intake(manifest, tmp_path / "repository")
    assert result["available_capacity_mw"] is None
    with pytest.raises(ValueError, match="outside"):
        validate_operator_intake(manifest, tmp_path)


def test_reconciliation_is_chronological_and_rejects_proximity_matches():
    outcomes = [
        {
            "request_id": "a",
            "decision_at": "2025-03-01T00:00:00Z",
            "offered_conditional_mw": 20.0,
        }
    ]
    predictions = [
        {
            "request_id": "a",
            "issued_at": "2025-02-01T00:00:00Z",
            "predicted_conditional_mw": 18.0,
            "identity_method": "operator_provided",
        },
        {
            "request_id": "a",
            "issued_at": "2025-04-01T00:00:00Z",
            "predicted_conditional_mw": 25.0,
            "identity_method": "exact",
        },
    ]
    result = reconcile_connection_outcomes(predictions, outcomes)
    assert result["matched_requests"] == 1
    assert result["mean_absolute_error_mw"] == 2.0
    assert result["operator_confirmed"] is False
