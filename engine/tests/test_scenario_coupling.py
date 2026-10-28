import pytest

from capacity_backtest.scenario_coupling import select_mock_scenario


def test_regional_risk_selects_stress_without_mw_derating() -> None:
    result = select_mock_scenario(
        0.8,
        known_outage=False,
        source_available=True,
        evidence_resolution="50hertz_control_area",
    )
    assert result.scenario_id == "high_regional_risk"
    assert result.physical_mw_adjustment is None


def test_invalid_probability_fails_closed() -> None:
    with pytest.raises(ValueError):
        select_mock_scenario(
            1.1,
            known_outage=False,
            source_available=True,
            evidence_resolution="control_area",
        )
