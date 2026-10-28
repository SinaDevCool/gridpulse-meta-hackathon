from capacity_backtest.data_center.contracts import ScheduledWorkloadAction, WorkloadActionKind
from capacity_backtest.data_center.phase2_adapter import map_portfolio_to_phase2
from capacity_backtest.data_center.portfolio import WorkloadPortfolio, evaluate_portfolio
from capacity_backtest.phase2.thermal_workload import CoolingConfig

from .test_data_center_contracts import workload
from .test_data_center_power_profiles import profile
from .test_data_center_workloads import INTERVALS


def test_job_deferred_and_recovery_energy_reconcile_with_phase2_backlog() -> None:
    job = workload()
    portfolio = evaluate_portfolio(
        WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS,
        (ScheduledWorkloadAction("delay", job.workload_id, 0, WorkloadActionKind.DELAY_START),),
        site_id="site-a",
    )
    result = map_portfolio_to_phase2(
        portfolio, INTERVALS, CoolingConfig(0, 0, 0), deadline_hours=4,
    )
    assert result.job_deferred_energy_mwh == result.job_recovery_energy_mwh
    assert result.aggregate_ending_backlog_mwh == 0
    assert result.reconciliation_error_mwh == 0
