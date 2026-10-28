"""Actual existing HTTP API -> job runner -> private MILP, with no database/network."""
from dataclasses import asdict
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from capacity_backtest.phase2.battery import BatteryConfig
from grid_data.api.app import create_app
from grid_data.api.executor import OperatorHealthExecutor
from grid_data.api.models import UserIdentity
from grid_data.api.models import FacilityPlanRequest
from capacity_backtest.application.transport_schema import facility_plan_transport_schema
from grid_data.api.store import InMemoryJobStore

from .test_application_facility import request


def test_http_contract_field_inventory_cannot_drift_from_engine():
    schema = facility_plan_transport_schema()
    api_schema = FacilityPlanRequest.model_json_schema()
    assert set(api_schema["properties"]) == set(schema["properties"])
    assert set(api_schema["required"]) == set(schema["required"])


def test_authenticated_http_executes_joint_solver_and_preserves_inputs(monkeypatch):
    monkeypatch.setenv("GRIDPULSE_JOB_DISPATCH_MODE", "inline")
    store = InMemoryJobStore()
    owner = UserIdentity(id=uuid4())
    def authenticated_owner():
        return owner
    executor = OperatorHealthExecutor(store, supabase_url="https://unused.invalid", service_role_key="unused")
    app = create_app(job_store=store, executor=executor, auth_dependency=authenticated_owner)
    payload = request()
    payload["batteries"] = [asdict(BatteryConfig("battery", 0.1, 0.2, 0.2, 0.02, 0.18))]
    payload["onsite_generation_mw"] = [0.001] * 4
    payload["fleet_gpu_capacity"] = 8
    payload = json.loads(json.dumps(payload))
    with TestClient(app) as client:
        submitted = client.post("/v1/jobs/facility-plan", json=payload)
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["job_id"]
        job = client.get(f"/v1/jobs/{job_id}").json()
        assert job["status"] == "succeeded", job
        assert job["input_payload"]["batteries"] == payload["batteries"]
        assert job["input_payload"]["onsite_generation_mw"] == [0.001] * 4
        result = job["result_payload"]["result"]
        assert result["status"] == "optimal"
        assert result["assessment"]["feasible"]
        assert result["battery_trajectories"][0]["resource_id"] == "battery"
        assert not result["automatic_live_dispatch_authorized"]
        duplicate = client.post("/v1/jobs/facility-plan", json=payload)
        assert duplicate.json()["job_id"] == job_id
        app.dependency_overrides[authenticated_owner] = lambda: UserIdentity(id=uuid4())
        assert client.get(f"/v1/jobs/{job_id}").status_code == 404
