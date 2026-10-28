import pytest

from grid_data.deflex import FlexibilityPolicy, dispatch_flexibility


def test_flexibility_is_bounded_and_deterministic():
    policy = FlexibilityPolicy(0.2, 2, 2, 2, 5, 10, minimum_reserve_soc_fraction=0.1)
    args = ([25.0] * 6, [30.0] * 6, [20.0] * 6, policy)
    first = dispatch_flexibility(*args)
    second = dispatch_flexibility(*args)
    assert first == second
    assert first["classification"] == "synthetic_benchmark"
    assert first["capacity_claim"] is False
    assert first["curtailed_or_shifted_mwh"] <= 2 * 5
    assert first["maximum_consecutive_interruption_hours"] <= 2


def test_unknown_or_misaligned_envelope_fails_closed():
    policy = FlexibilityPolicy(0.1, 1, 1, 1, 0, 0)
    with pytest.raises(ValueError, match="aligned"):
        dispatch_flexibility([10], [10], [], policy)


def test_critical_load_and_ramp_shortfall_are_reported() -> None:
    policy = FlexibilityPolicy(
        0.2,
        1,
        1,
        1,
        0,
        0,
        ramp_limit_mw_per_hour=1,
        critical_load_fraction=0.8,
    )
    result = dispatch_flexibility([1, 10], [20, 20], [20, 20], policy)
    assert result["ramp_unserved_mwh"] > 0
    assert result["critical_unserved_mwh"] > 0
    assert result["real_network_validated"] is False
    assert result["connection_capacity_claim"] is False
