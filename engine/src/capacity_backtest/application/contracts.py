"""Canonical transport-contract registry published with the analytical wheel."""

from __future__ import annotations

import hashlib
import json

from .accounting import ACCOUNTING_REQUEST_SCHEMA, ACCOUNTING_RESULT_SCHEMA
from .capacity import (
    CAPACITY_REQUIREMENT_REQUEST_SCHEMA,
    CAPACITY_REQUIREMENT_RESULT_SCHEMA,
)
from .evidence import EVIDENCE_PACKAGE_REQUEST_SCHEMA, EVIDENCE_PACKAGE_RESULT_SCHEMA
from .experiments import EXPERIMENT_REQUEST_SCHEMA, EXPERIMENT_RESULT_SCHEMA
from .facility import FACILITY_PLAN_REQUEST_SCHEMA, FACILITY_PLAN_RESULT_SCHEMA
from .fca import FCA_INTERVAL_REQUEST_SCHEMA, FCA_INTERVAL_RESULT_SCHEMA
from .market import MARKET_QUALIFICATION_REQUEST_SCHEMA, MARKET_QUALIFICATION_RESULT_SCHEMA
from .replay import HISTORICAL_REPLAY_REQUEST_SCHEMA, HISTORICAL_REPLAY_RESULT_SCHEMA
from .rolling import (
    CHRONOLOGICAL_SHADOW_REQUEST_SCHEMA,
    CHRONOLOGICAL_SHADOW_RESULT_SCHEMA,
    ROLLING_PLAN_REQUEST_SCHEMA,
    ROLLING_PLAN_RESULT_SCHEMA,
)
from .shadow import SHADOW_VERIFICATION_REQUEST_SCHEMA, SHADOW_VERIFICATION_RESULT_SCHEMA
from .transport_schema import facility_plan_transport_schema
from .uncertainty import UNCERTAINTY_REQUEST_SCHEMA, UNCERTAINTY_RESULT_SCHEMA

CONTRACT_MANIFEST_SCHEMA = "gridpulse-analytics-contract-manifest-v1"


def contract_manifest() -> dict[str, object]:
    contracts = [
        {"operation": "facility_accounting", "request_schema": ACCOUNTING_REQUEST_SCHEMA,
         "result_schema": ACCOUNTING_RESULT_SCHEMA, "endpoint": "/v1/jobs/facility-accounting"},
        {"operation": "chronological_shadow", "request_schema": CHRONOLOGICAL_SHADOW_REQUEST_SCHEMA,
         "result_schema": CHRONOLOGICAL_SHADOW_RESULT_SCHEMA, "endpoint": "/v1/jobs/rolling-facility-plan"},
        {"operation": "facility_experiment", "request_schema": EXPERIMENT_REQUEST_SCHEMA,
         "result_schema": EXPERIMENT_RESULT_SCHEMA, "endpoint": "/v1/jobs/facility-experiment"},
        {
            "operation": "capacity_requirement",
            "request_schema": CAPACITY_REQUIREMENT_REQUEST_SCHEMA,
            "result_schema": CAPACITY_REQUIREMENT_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/capacity-requirement",
        },
        {
            "operation": "facility_plan",
            "request_schema": FACILITY_PLAN_REQUEST_SCHEMA,
            "result_schema": FACILITY_PLAN_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/facility-plan",
        },
        {
            "operation": "fca_interval",
            "request_schema": FCA_INTERVAL_REQUEST_SCHEMA,
            "result_schema": FCA_INTERVAL_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/fca-interval",
        },
        {
            "operation": "market_qualification",
            "request_schema": MARKET_QUALIFICATION_REQUEST_SCHEMA,
            "result_schema": MARKET_QUALIFICATION_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/market-qualification",
        },
        {
            "operation": "rolling_facility_plan",
            "request_schema": ROLLING_PLAN_REQUEST_SCHEMA,
            "result_schema": ROLLING_PLAN_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/rolling-facility-plan",
        },
        {
            "operation": "facility_uncertainty",
            "request_schema": UNCERTAINTY_REQUEST_SCHEMA,
            "result_schema": UNCERTAINTY_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/facility-uncertainty",
        },
        {
            "operation": "facility_historical_replay",
            "request_schema": HISTORICAL_REPLAY_REQUEST_SCHEMA,
            "result_schema": HISTORICAL_REPLAY_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/facility-historical-replay",
        },
        {
            "operation": "operator_enquiry_package",
            "request_schema": EVIDENCE_PACKAGE_REQUEST_SCHEMA,
            "result_schema": EVIDENCE_PACKAGE_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/operator-enquiry-package",
        },
        {
            "operation": "shadow_verification",
            "request_schema": SHADOW_VERIFICATION_REQUEST_SCHEMA,
            "result_schema": SHADOW_VERIFICATION_RESULT_SCHEMA,
            "endpoint": "/v1/jobs/shadow-verification",
        },
    ]
    schemas = {FACILITY_PLAN_REQUEST_SCHEMA: facility_plan_transport_schema()}
    encoded = json.dumps({"contracts": contracts, "transport_schemas": schemas}, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": CONTRACT_MANIFEST_SCHEMA,
        "contracts": contracts,
        "transport_schemas": schemas,
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
    }
