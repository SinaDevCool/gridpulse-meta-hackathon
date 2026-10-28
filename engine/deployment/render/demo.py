"""Fixed public synthetic demonstration; never accepts jobs or customer inputs."""
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from capacity_backtest.application import run_facility_plan
from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.contracts import AIWorkload, WorkloadKind, WorkloadSLA
from capacity_backtest.data_center.facility import FacilityConfig
from capacity_backtest.data_center.power_profiles import PiecewiseLinearPowerProfile, PowerThroughputPoint
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase2.battery import BatteryConfig


def synthetic_request():
    truth = TruthClass.SYNTHETIC_DEMONSTRATION
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cutoff = "2025-12-31T00:00:00+00:00"
    jobs = [AIWorkload(
        workload_id=f"synthetic-{i}", tenant_id="demo", workload_kind=WorkloadKind.TRAINING,
        earliest_start=start.isoformat(), nominal_gpu_count=8, minimum_gpu_count=8,
        maximum_gpu_count=8, nominal_power_mw=0.08, minimum_power_cap_mw=0.04,
        expected_duration_minutes=60, checkpoint_duration_minutes=15, restart_duration_minutes=15,
        geographic_movement_permitted=False, allowed_site_ids=("demo-site",),
        data_residency_regions=("DE",),
        sla=WorkloadSLA("2026-01-01T04:00:00+00:00", 0.5, 0.5, 0, None, 1000),
        truth_class=truth, evidence_cutoff=cutoff,
    ) for i in range(5)]
    facility = FacilityConfig(
        facility_id="synthetic-facility", site_id="demo-site", import_limit_mw=1,
        cooling_baseline_mw=0.02, cooling_load_factor=0.2, networking_power_mw=0.01,
        storage_power_mw=0.01, fixed_auxiliary_power_mw=0.01, ups_loss_fraction=0.05,
        distribution_loss_fraction=0.05, reactive_min_mvar=-1, reactive_max_mvar=1,
        minimum_power_factor=0.95, maximum_phase_unbalance_fraction=0.1,
        pue_assumption=1.3, heat_reuse_mw=0, truth_class=truth,
    )
    requirement = FlexibilityRequirement(
        "demo-requirement", "demo-site", "pcc", "capacity", "gridpulse-capacity-envelope-result-v1",
        "a" * 64, 1, 0.97, 1, 0.03, 0.03, 3600, 60, 1, 10, 10,
        0, 1, 1.0, None, cutoff, truth, False, False, True,
    )
    return json.loads(json.dumps({
        "schema_version": "gridpulse-facility-plan-request-v1", "portfolio_id": "synthetic-demo",
        "requirement": asdict(requirement), "facility": asdict(facility),
        "intervals": [{"index": i, "start": (start + timedelta(minutes=15*i)).isoformat(),
                       "duration_minutes": 15} for i in range(96)],
        "workloads": [asdict(job) for job in jobs],
        "profiles": [asdict(PiecewiseLinearPowerProfile(
            f"profile-{job.workload_id}", job.workload_id,
            (PowerThroughputPoint(8, 0.04, 0.5), PowerThroughputPoint(8, 0.08, 1)), truth,
        )) for job in jobs],
        "batteries": [asdict(BatteryConfig("demo-battery", 0.1, 0.2, 0.2, 0.02, 0.18))],
        "policy": {"event_intervals": [i < 4 for i in range(96)],
                   "battery_temperature_c": [20.0]*96, "solver_time_limit_seconds": 30},
        "economics": {"import_price_eur_per_mwh": [100.0 if i < 4 else 10.0 for i in range(96)]},
        "cooling": {"baseline_power_mw": 0.02, "maximum_reduction_mw": 0.0, "thermal_capacity_mwh": 0.0},
        "onsite_generation_mw": [0.001]*96, "fleet_gpu_capacity": 40, "idle_gpu_power_watts": 70,
    }))


@asynccontextmanager
async def lifespan(app):
    request = synthetic_request()
    payload = run_facility_plan(request)
    result = payload["result"]
    if (result["status"] not in {"optimal", "feasible_not_proven_optimal"}
            or not result.get("assessment", {}).get("feasible") or result.get("diagnostics")):
        raise RuntimeError("Synthetic MILP did not pass physical acceptance")
    app.state.result = payload
    app.state.request = request
    yield


app = FastAPI(title="GridPulse synthetic MILP pilot", lifespan=lifespan, docs_url=None, redoc_url=None)
# All exposed content is fixed public synthetic data; no cookies or credentials.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])


@app.get("/healthz")
def health():
    return {"ready": True, "mode": "synthetic_only", "customer_inputs": False}


@app.get("/result")
def result():
    return app.state.result


@app.get("/assessment")
def assessment():
    return {"request": app.state.request, "result": app.state.result}


@app.get("/", response_class=HTMLResponse)
def home():
    value = app.state.result
    result = value["result"]
    return f"""<!doctype html><html lang=en><meta charset=utf-8>
    <meta name=viewport content='width=device-width,initial-scale=1'><title>GridPulse MILP pilot</title>
    <style>body{{font:17px system-ui;max-width:760px;margin:64px auto;padding:24px;color:#173249;background:#f4f7fa}}
    article{{background:white;padding:32px;border:1px solid #ccd9e2;border-radius:12px}}small{{color:#536979}}</style>
    <article><small>GRIDPULSE · SYNTHETIC QUALIFICATION ONLY</small><h1>Real MILP. Fixed demonstration.</h1>
    <p>96 fifteen-minute intervals · 5 synthetic workloads · battery and onsite generation.</p>
    <p>Solver: <strong>{result['solver']}</strong><br>Status: <strong>{result['status']}</strong><br>
    Physical replay: <strong>accepted</strong><br>Engine: {value['engine_version']}</p>
    <p>This result is calculated once at startup. No customer inputs, production charts, database or equipment commands are connected.</p>
    <a href=/result>Inspect the complete calculation JSON</a><p><small>Free hosting can sleep or restart. This is not a production service or verified facility assessment.</small></p></article></html>"""
