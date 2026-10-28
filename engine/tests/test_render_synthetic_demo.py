"""Same fixed synthetic fixture deployed by the isolated Render pilot."""
from fastapi.testclient import TestClient
from deployment.render.demo import app


def test_fixed_demo_runs_real_milp_and_has_no_solve_endpoint():
    with TestClient(app) as client:
        assert client.get("/healthz").json()["customer_inputs"] is False
        payload = client.get("/result").json()
        result = payload["result"]
        assert result["solver"] == "scipy-highs-milp"
        assert result["assessment"]["feasible"]
        assert not result["diagnostics"]
        assert len(result["intervals"]) == 96
        assert len(result["portfolio"]["workload_trajectories"]) == 5
        assert payload["automatic_live_dispatch_authorized"] is False
        assert client.get("/result").json()["result_fingerprint"] == payload["result_fingerprint"]
        assert client.post("/result", json={"workloads": []}).status_code == 405
        assert client.post("/v1/jobs/facility-plan", json={}).status_code == 404
        snapshot = client.get("/assessment", headers={"Origin": "https://example.invalid"})
        assert snapshot.headers["access-control-allow-origin"] == "*"
        assert snapshot.json()["result"]["result_fingerprint"] == payload["result_fingerprint"]
        assert snapshot.json()["request"]["facility"]["facility_id"] == "synthetic-facility"
        assert client.post("/assessment", json={}).status_code == 405
