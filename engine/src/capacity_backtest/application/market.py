"""Versioned provider-neutral market qualification and settlement boundary."""

from __future__ import annotations

from typing import Any

from capacity_backtest.data_center.uncertainty import (
    ScenarioOutcome,
    UncertainFlexibilityAssessment,
)
from capacity_backtest.domain.evidence import EvidenceReference
from capacity_backtest.market.contracts import MarketDirection, MarketProduct, PaymentType
from capacity_backtest.market.eligibility import assess_market_eligibility
from capacity_backtest.market.settlement import settle_delivery
from capacity_backtest.phase1.risk import RiskPolicy

from .facility import ENGINE_VERSION, _fingerprint, _requirement, _serialize, _truth
from .uncertainty import UNCERTAINTY_RESULT_SCHEMA

MARKET_QUALIFICATION_REQUEST_SCHEMA = "gridpulse-market-qualification-request-v1"
MARKET_QUALIFICATION_RESULT_SCHEMA = "gridpulse-market-qualification-application-result-v1"


def _evidence(row: dict[str, Any]) -> EvidenceReference:
    values = dict(row)
    values["truth_class"] = _truth(values["truth_class"])
    values["limitations"] = tuple(values.get("limitations", ()))
    reference = EvidenceReference(**values)
    reference.validate()
    return reference


def _product(row: dict[str, Any]) -> MarketProduct:
    values = dict(row)
    values["direction"] = MarketDirection(values["direction"])
    values["payment_type"] = PaymentType(values["payment_type"])
    values["truth_class"] = _truth(values["truth_class"])
    values["evidence"] = tuple(_evidence(item) for item in values.get("evidence", ()))
    product = MarketProduct(**values)
    product.validate()
    return product


def _uncertainty(row: dict[str, Any]) -> UncertainFlexibilityAssessment:
    if row.get("schema_version") != UNCERTAINTY_RESULT_SCHEMA:
        raise ValueError("market qualification requires a canonical uncertainty result")
    if row.get("capacity_claim") is not False or row.get("automatic_live_dispatch_authorized") is not False:
        raise ValueError("uncertainty result crossed the nonclaim or dispatch boundary")
    supplied_fingerprint = str(row.get("result_fingerprint", ""))
    fingerprint_input = dict(row)
    fingerprint_input.pop("result_fingerprint", None)
    if len(supplied_fingerprint) != 64 or _fingerprint(fingerprint_input) != supplied_fingerprint:
        raise ValueError("uncertainty result fingerprint is invalid")
    result = row.get("result")
    if not isinstance(result, dict):
        raise TypeError("uncertainty result payload is invalid")
    values = dict(result)
    values["policy"] = RiskPolicy(values["policy"])
    values["outcomes"] = tuple(ScenarioOutcome(**item) for item in values.get("outcomes", ()))
    values["blockers"] = tuple(values.get("blockers", ()))
    return UncertainFlexibilityAssessment(**values)


def run_market_qualification(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != MARKET_QUALIFICATION_REQUEST_SCHEMA:
        raise ValueError("unsupported market-qualification request schema")
    product = _product(request["product"])
    requirement = _requirement(request["requirement"])
    uncertainty = _uncertainty(request["uncertainty"])
    eligibility = assess_market_eligibility(product, requirement, uncertainty)
    settlement_input = request.get("settlement")
    settlement = None
    if settlement_input is not None:
        if not eligibility.eligible:
            raise ValueError("settlement is blocked because the product is not technically eligible")
        settlement = settle_delivery(
            product,
            offered_mw=float(settlement_input["offered_mw"]),
            availability_hours=float(settlement_input["availability_hours"]),
            requested_mwh=float(settlement_input["requested_mwh"]),
            verified_delivered_mwh=float(settlement_input["verified_delivered_mwh"]),
        )
    payload = {
        "schema_version": MARKET_QUALIFICATION_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(request),
        "truth_class": product.truth_class.value,
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "eligibility": _serialize(eligibility),
        "settlement": _serialize(settlement),
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
