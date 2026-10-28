from capacity_backtest.data_center.shadow_monitor import assess_shadow_divergence


def test_shadow_divergence_drives_existing_fail_safe() -> None:
    normal = assess_shadow_divergence((10, 10), (10.1, 9.9), uncertainty_band_mw=(0.2, 0.2), evaluated_at="2026-01-01T00:00:00+00:00")
    assert normal.classification == "normal" and normal.conditional_flexibility_allowed
    failed = assess_shadow_divergence((10, 10, 10), (12, 12, 12), uncertainty_band_mw=(0.2, 0.2, 0.2), evaluated_at="2026-01-01T00:00:00+00:00")
    assert failed.classification == "safe_limit"
    assert not failed.conditional_flexibility_allowed
    assert failed.final_operational_state.value == "safe_limit"
