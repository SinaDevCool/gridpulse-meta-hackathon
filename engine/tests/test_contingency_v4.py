from capacity_backtest.contingency_v4 import (
    dc_injection_sensitivity,
    select_contingencies_v4,
)
from grid_data.berlin_synthetic_capacity import BERLIN_NODES, build_berlin_synthetic_model


def test_v4_selector_uses_electrical_sensitivity_and_preserves_reduction() -> None:
    model = build_berlin_synthetic_model()
    candidate = BERLIN_NODES[0][0]
    sensitivity = dc_injection_sensitivity(model, candidate)
    selection = select_contingencies_v4(model, candidate)
    assert set(sensitivity) == {branch["id"] for branch in model.branches}
    assert selection["selected_case_count"] < selection["full_case_count"]
    assert selection["reduction_ratio"] >= 0.5
    assert selection["physics_verification_required"] is True
    assert selection["capacity_claim"] is False
