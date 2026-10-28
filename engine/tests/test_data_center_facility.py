from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.facility import FacilityConfig, build_facility_trajectory
from capacity_backtest.data_center.portfolio import WorkloadPortfolio, evaluate_portfolio

from .test_data_center_contracts import workload
from .test_data_center_power_profiles import profile
from .test_data_center_workloads import INTERVALS


def config(**changes):
    values = {
        "facility_id": "facility", "site_id": "site-a", "import_limit_mw": 1,
        "cooling_baseline_mw": 0.02, "cooling_load_factor": 0.2,
        "networking_power_mw": 0.01, "storage_power_mw": 0.01,
        "fixed_auxiliary_power_mw": 0.01, "ups_loss_fraction": 0.05,
        "distribution_loss_fraction": 0.05, "reactive_min_mvar": -1,
        "reactive_max_mvar": 1, "minimum_power_factor": 0.95,
        "maximum_phase_unbalance_fraction": 0.1, "pue_assumption": 1.3,
        "heat_reuse_mw": 0, "truth_class": TruthClass.SYNTHETIC_DEMONSTRATION,
    }
    values.update(changes)
    return FacilityConfig(**values)


def test_facility_import_includes_non_it_loads_and_losses() -> None:
    job = workload()
    portfolio = evaluate_portfolio(WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS, (), site_id="site-a")
    result = build_facility_trajectory(config(), INTERVALS, portfolio)
    first = result.points[0]
    assert first.grid_import_mw > first.it_power_mw
    assert first.cooling_power_mw > 0 and first.auxiliary_power_mw > 0 and first.losses_mw > 0
    assert all(item.passed for item in result.phase_power_assessments)


def test_facility_import_limit_violation_is_explicit() -> None:
    job = workload()
    portfolio = evaluate_portfolio(WorkloadPortfolio("p", (job,)), {job.workload_id: profile()}, INTERVALS, (), site_id="site-a")
    result = build_facility_trajectory(config(import_limit_mw=0.05), INTERVALS, portfolio)
    assert result.import_limit_violation_count > 0
