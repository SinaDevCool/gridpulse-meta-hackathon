from dataclasses import replace

from capacity_backtest.data_center.contracts import (
    ScheduledWorkloadAction,
    WorkloadActionKind,
)
from capacity_backtest.data_center.portfolio import WorkloadPortfolio, evaluate_portfolio

from .test_data_center_contracts import workload
from .test_data_center_power_profiles import profile
from .test_data_center_workloads import INTERVALS


def test_portfolio_conserves_work_and_fingerprints_deterministically() -> None:
    job = workload()
    portfolio = WorkloadPortfolio("portfolio", (job,))
    first = evaluate_portfolio(portfolio, {job.workload_id: profile()}, INTERVALS, (), site_id="site-a")
    second = evaluate_portfolio(portfolio, {job.workload_id: profile()}, INTERVALS, (), site_id="site-a")
    assert first.ending_backlog_mwh == 0
    assert not first.sla_violations
    assert first.fingerprint() == second.fingerprint()


def test_delayed_work_produces_backlog_rebound_and_sla_consequence() -> None:
    job = workload(sla=replace(workload().sla, deadline="2026-01-01T01:00:00+00:00"))
    actions = (ScheduledWorkloadAction("delay", job.workload_id, 0, WorkloadActionKind.DELAY_START),)
    result = evaluate_portfolio(
        WorkloadPortfolio("portfolio", (job,)), {job.workload_id: profile()},
        INTERVALS, actions, site_id="site-a",
    )
    assert result.power_points[0].deferred_power_mw > 0
    assert result.sla_violations
    assert result.total_sla_penalty_eur == job.sla.penalty_eur
