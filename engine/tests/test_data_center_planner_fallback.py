from capacity_backtest.data_center.planner import plan_facility_with_fallback

from .test_data_center_optimizer import inputs


def test_planner_accepts_verified_plan_and_falls_back_on_infeasibility() -> None:
    accepted = plan_facility_with_fallback(**inputs())
    assert accepted.accepted and not accepted.used_fallback
    values = inputs(required=0.5)
    failed = plan_facility_with_fallback(**values)
    assert failed.used_fallback and failed.fallback is not None
    assert not failed.fallback.conditional_flexibility_enabled
    assert not failed.automatic_live_dispatch_authorized
