from dataclasses import asdict

import pytest

from capacity_backtest.application import (
    MARKET_QUALIFICATION_REQUEST_SCHEMA,
    run_facility_uncertainty,
    run_market_qualification,
)

from .test_application_uncertainty import request as uncertainty_request
from .test_data_center_flexibility_assessment import requirement
from .test_market_products import product


def request() -> dict[str, object]:
    return {
        "schema_version": MARKET_QUALIFICATION_REQUEST_SCHEMA,
        "product": asdict(product()),
        "requirement": asdict(requirement()),
        "uncertainty": run_facility_uncertainty(uncertainty_request()),
        "settlement": {
            "offered_mw": 0.05,
            "availability_hours": 2,
            "requested_mwh": 0.1,
            "verified_delivered_mwh": 0.08,
        },
    }


def test_market_boundary_qualifies_and_settles_verified_delivery_only() -> None:
    result = run_market_qualification(request())
    assert result["eligibility"]["eligible"] is True
    assert result["settlement"]["delivered_mwh"] == pytest.approx(0.08)
    assert result["capacity_claim"] is False
    assert result["automatic_live_dispatch_authorized"] is False
    assert len(result["result_fingerprint"]) == 64


def test_market_boundary_blocks_settlement_when_product_is_ineligible() -> None:
    payload = request()
    payload["product"]["minimum_bid_mw"] = 1
    with pytest.raises(ValueError, match="not technically eligible"):
        run_market_qualification(payload)
