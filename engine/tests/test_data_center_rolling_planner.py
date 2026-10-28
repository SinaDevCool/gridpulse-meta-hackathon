import pytest

from capacity_backtest.data_center.rolling_planner import RollingPlanningWindow, run_rolling_planner
from capacity_backtest.data_center.uncertainty import UncertaintyScenario

from .test_data_center_optimizer import inputs


def test_rolling_planner_is_chronological_and_preserves_safe_fallback() -> None:
    scenario = (UncertaintyScenario("s", 1, (20.0,) * 4, (0.0,) * 4),)
    windows = (
        RollingPlanningWindow("w1", "2025-12-31T00:00:00+00:00", "a" * 64, scenario, "initial"),
        RollingPlanningWindow("w2", "2025-12-31T01:00:00+00:00", "b" * 64, scenario, "forecast_revision"),
    )
    result = run_rolling_planner(windows, **inputs())
    assert result.accepted_revisions == 1
    assert result.fallback_count == 0
    assert not result.automatic_live_dispatch_authorized


def test_rolling_planner_rejects_cutoff_reversal() -> None:
    scenario = (UncertaintyScenario("s", 1, (20.0,) * 4, (0.0,) * 4),)
    windows = (
        RollingPlanningWindow("w1", "2025-12-31T01:00:00+00:00", "a" * 64, scenario, "initial"),
        RollingPlanningWindow("w2", "2025-12-31T00:00:00+00:00", "b" * 64, scenario, "revision"),
    )
    with pytest.raises(ValueError, match="chronological"):
        run_rolling_planner(windows, **inputs())
