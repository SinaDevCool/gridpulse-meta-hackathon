from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.assessment import assess_facility_flexibility
from capacity_backtest.data_center.contracts import ScheduledWorkloadAction, WorkloadActionKind
from capacity_backtest.data_center.facility import build_facility_trajectory
from capacity_backtest.data_center.phase2_adapter import map_portfolio_to_phase2
from capacity_backtest.data_center.portfolio import WorkloadPortfolio, evaluate_portfolio
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase2.thermal_workload import CoolingConfig

from .test_data_center_contracts import workload
from .test_data_center_facility import config
from .test_data_center_power_profiles import profile
from .test_data_center_workloads import INTERVALS


def requirement(required=0.05, rebound=1.0):
    return FlexibilityRequirement(
        "req", "site-a", "pcc", "capacity", "gridpulse-capacity-envelope-result-v1",
        "a" * 64, 1, 1 - required, 1, required, required, 3600, 60, 1, 10, 10,
        0, 1, rebound, None, "2025-12-31T00:00:00+00:00",
        TruthClass.SYNTHETIC_DEMONSTRATION, False, False, True,
    )


def trajectories():
    job = workload()
    base = evaluate_portfolio(WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS, (), site_id="site-a")
    scheduled = evaluate_portfolio(
        WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS,
        (ScheduledWorkloadAction("delay", job.workload_id, 0, WorkloadActionKind.DELAY_START),),
        site_id="site-a",
    )
    return (
        base, scheduled, build_facility_trajectory(config(), INTERVALS, base),
        build_facility_trajectory(config(), INTERVALS, scheduled),
        map_portfolio_to_phase2(scheduled, INTERVALS, CoolingConfig(0, 0, 0), deadline_hours=4),
    )


def test_deterministic_schedule_can_meet_requirement() -> None:
    _base, scheduled, base_facility, scheduled_facility, aggregate = trajectories()
    result = assess_facility_flexibility(
        requirement(), INTERVALS, base_facility, scheduled_facility, scheduled, aggregate,
        event_intervals=(True, False, False, False),
    )
    assert result.feasible
    assert result.delivered_reduction_mw >= result.required_reduction_mw
    assert result.automatic_live_dispatch_authorized is False


def test_shortfall_and_rebound_are_explicit_blockers() -> None:
    _base, scheduled, base_facility, scheduled_facility, aggregate = trajectories()
    result = assess_facility_flexibility(
        requirement(required=0.5, rebound=0), INTERVALS, base_facility,
        scheduled_facility, scheduled, aggregate, event_intervals=(True, False, False, False),
    )
    assert not result.feasible
    assert "flexibility_shortfall" in result.blockers
    assert "rebound_limit_exceeded" in result.blockers
