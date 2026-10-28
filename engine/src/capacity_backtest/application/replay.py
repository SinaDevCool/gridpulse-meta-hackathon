"""Versioned historical replay boundary over canonical frozen trajectories."""

from __future__ import annotations

from typing import Any

from capacity_backtest.data_center.backtest import HistoricalObservation, run_historical_backtest
from capacity_backtest.data_center.contracts import PlanningInterval
from capacity_backtest.data_center.economics import EconomicTariff
from capacity_backtest.data_center.facility import FacilityPowerPoint, FacilityPowerTrajectory
from capacity_backtest.data_center.portfolio import (
    PortfolioPowerPoint,
    PortfolioTrajectory,
    SLAViolation,
)

from .facility import ENGINE_VERSION, _fingerprint, _serialize

HISTORICAL_REPLAY_REQUEST_SCHEMA = "gridpulse-facility-historical-replay-request-v1"
HISTORICAL_REPLAY_RESULT_SCHEMA = "gridpulse-facility-historical-replay-application-result-v1"


def _facility(row: dict[str, Any]) -> FacilityPowerTrajectory:
    return FacilityPowerTrajectory(
        facility_id=str(row["facility_id"]),
        points=tuple(FacilityPowerPoint(**item) for item in row["points"]),
        phase_power_assessments=(),
        maximum_grid_import_mw=float(row["maximum_grid_import_mw"]),
        import_limit_violation_count=int(row.get("import_limit_violation_count", 0)),
    )


def _portfolio(row: dict[str, Any]) -> PortfolioTrajectory:
    return PortfolioTrajectory(
        portfolio_id=str(row["portfolio_id"]),
        workload_trajectories=(),
        power_points=tuple(PortfolioPowerPoint(**item) for item in row["power_points"]),
        sla_violations=tuple(SLAViolation(**item) for item in row.get("sla_violations", ())),
        total_sla_penalty_eur=float(row["total_sla_penalty_eur"]),
        ending_backlog_mwh=float(row.get("ending_backlog_mwh", 0)),
    )


def run_facility_historical_replay(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != HISTORICAL_REPLAY_REQUEST_SCHEMA:
        raise ValueError("unsupported facility historical-replay request schema")
    result = run_historical_backtest(
        planning_cutoff=str(request["planning_cutoff"]),
        intervals=tuple(PlanningInterval(**item) for item in request["intervals"]),
        baseline=_facility(request["baseline"]),
        planned=_facility(request["planned"]),
        portfolio=_portfolio(request["portfolio"]),
        observations=tuple(HistoricalObservation(**item) for item in request["observations"]),
        tariff=EconomicTariff(**{**request["tariff"], "energy_price_eur_per_mwh": tuple(request["tariff"]["energy_price_eur_per_mwh"])}),
        event_intervals=tuple(request["event_intervals"]),
        required_reduction_mw=float(request["required_reduction_mw"]),
        battery_throughput_mwh=float(request.get("battery_throughput_mwh", 0)),
    )
    payload = {
        "schema_version": HISTORICAL_REPLAY_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(request),
        "capacity_claim": False,
        "automatic_live_dispatch_authorized": False,
        "result": _serialize(result),
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
