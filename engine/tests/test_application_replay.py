from dataclasses import asdict

import pytest

from capacity_backtest.application import (
    HISTORICAL_REPLAY_REQUEST_SCHEMA,
    run_facility_historical_replay,
)
from capacity_backtest.data_center.backtest import HistoricalObservation
from capacity_backtest.data_center.facility import build_facility_trajectory
from capacity_backtest.data_center.portfolio import WorkloadPortfolio, evaluate_portfolio

from .test_data_center_contracts import workload
from .test_data_center_facility import config
from .test_data_center_power_profiles import profile
from .test_data_center_workloads import INTERVALS


def request() -> dict[str, object]:
    job = workload()
    portfolio = evaluate_portfolio(
        WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS, (), site_id="site-a"
    )
    facility = build_facility_trajectory(config(), INTERVALS, portfolio)
    observations = tuple(
        HistoricalObservation(
            index, interval.start, "2026-01-02T00:00:00+00:00",
            point.grid_import_mw - (0.03 if index == 0 else 0),
        )
        for index, (interval, point) in enumerate(zip(INTERVALS, facility.points))
    )
    return {
        "schema_version": HISTORICAL_REPLAY_REQUEST_SCHEMA,
        "planning_cutoff": "2025-12-31T00:00:00+00:00",
        "intervals": [asdict(item) for item in INTERVALS],
        "baseline": asdict(facility),
        "planned": asdict(facility),
        "portfolio": asdict(portfolio),
        "observations": [asdict(item) for item in observations],
        "tariff": {
            "energy_price_eur_per_mwh": [10, 10, 10, 10],
            "demand_charge_eur_per_mw": 5,
            "battery_wear_eur_per_mwh": 1,
            "market_payment_eur_per_mwh": 100,
            "non_delivery_penalty_eur_per_mwh": 200,
        },
        "event_intervals": [True, False, False, False],
        "required_reduction_mw": 0.03,
    }


def test_replay_boundary_is_deterministic_and_keeps_economics_separate() -> None:
    first = run_facility_historical_replay(request())
    assert first == run_facility_historical_replay(request())
    assert first["result"]["delivery_accuracy"] == pytest.approx(1)
    assert first["result"]["economics"]["market_revenue_eur"] > 0
    assert first["capacity_claim"] is False


def test_replay_boundary_rejects_information_leakage() -> None:
    payload = request()
    payload["planning_cutoff"] = "2026-01-03T00:00:00+00:00"
    with pytest.raises(ValueError, match="leaked"):
        run_facility_historical_replay(payload)
