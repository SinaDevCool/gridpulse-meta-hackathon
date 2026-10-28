import pytest

from capacity_backtest.data_center.backtest import HistoricalObservation, run_historical_backtest
from capacity_backtest.data_center.economics import EconomicTariff
from capacity_backtest.data_center.facility import build_facility_trajectory
from capacity_backtest.data_center.portfolio import WorkloadPortfolio, evaluate_portfolio

from .test_data_center_contracts import workload
from .test_data_center_facility import config
from .test_data_center_power_profiles import profile
from .test_data_center_workloads import INTERVALS
from capacity_backtest.data_center.contracts import PlanningInterval
from capacity_backtest.data_center.economics import calculate_economics
from datetime import datetime, timedelta, timezone


def test_quarter_hour_fixed_schedule_preserves_work_energy_and_peak_cost():
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    outcomes = []
    for minutes in (60, 15):
        intervals = tuple(PlanningInterval(i, (origin + timedelta(minutes=i * minutes)).isoformat(), minutes)
                          for i in range(240 // minutes))
        job = workload(expected_duration_minutes=120)
        portfolio = evaluate_portfolio(WorkloadPortfolio("p", (job,)), {job.workload_id: profile()},
                                       intervals, (), site_id="site-a")
        facility = build_facility_trajectory(config(), intervals, portfolio)
        economics = calculate_economics(
            intervals, facility, facility, portfolio,
            EconomicTariff((100,) * len(intervals), 5, 0, 0, 0),
            requested_reduction_mw=(0,) * len(intervals),
            delivered_reduction_mw=(0,) * len(intervals))
        outcomes.append((economics.energy_cost_eur, economics.demand_charge_eur,
                         portfolio.workload_trajectories[0].points[-1].remaining_work_hours))
    assert outcomes[1] == pytest.approx(outcomes[0])
    assert outcomes[1][2] == 0


def test_backtest_enforces_cutoff_and_accounts_costs() -> None:
    job = workload()
    portfolio = evaluate_portfolio(
        WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS, (), site_id="site-a"
    )
    facility = build_facility_trajectory(config(), INTERVALS, portfolio)
    observations = tuple(
        HistoricalObservation(i, interval.start, "2026-01-02T00:00:00+00:00", point.grid_import_mw - (0.03 if i == 0 else 0))
        for i, (interval, point) in enumerate(zip(INTERVALS, facility.points))
    )
    result = run_historical_backtest(
        "2025-12-31T00:00:00+00:00", INTERVALS, facility, facility, portfolio,
        observations, EconomicTariff((10, 10, 10, 10), 5, 1, 100, 200),
        event_intervals=(True, False, False, False), required_reduction_mw=0.03,
    )
    assert result.delivery_accuracy == pytest.approx(1)
    assert result.economics.market_revenue_eur > 0
    assert not result.capacity_claim


def test_backtest_rejects_future_leakage() -> None:
    job = workload()
    portfolio = evaluate_portfolio(WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS, (), site_id="site-a")
    facility = build_facility_trajectory(config(), INTERVALS, portfolio)
    observations = tuple(HistoricalObservation(i, x.start, "2026-01-01T04:00:00+00:00", 0) for i, x in enumerate(INTERVALS))
    with pytest.raises(ValueError, match="leaked"):
        run_historical_backtest("2026-01-02T00:00:00+00:00", INTERVALS, facility, facility, portfolio, observations, EconomicTariff((0, 0, 0, 0), 0, 0, 0, 0), event_intervals=(False,) * 4, required_reduction_mw=0)



def test_mixed_duration_accounting_integrates_each_interval():
    from capacity_backtest.data_center.economics import integrate_energy_cost
    intervals = (PlanningInterval(0, "2026-01-01T00:00:00Z", 15),
                 PlanningInterval(1, "2026-01-01T00:15:00Z", 60))
    assert integrate_energy_cost(intervals, (4, 2), (100, 200)) == pytest.approx(500)
    with pytest.raises(ValueError):
        integrate_energy_cost(intervals, (float("nan"), 2), (100, 200))
