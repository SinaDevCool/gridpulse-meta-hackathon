import pytest

from capacity_backtest.gridcare_outputs import GridCareOutput, unavailable_gridcare_output


def test_default_output_keeps_four_layers_separate() -> None:
    result = unavailable_gridcare_output().as_dict()
    assert result["layers_blended"] is False
    assert result["layers"]["operator_confirmed_capacity"]["available_capacity_mw"] is None


def test_synthetic_layer_cannot_be_promoted() -> None:
    base = unavailable_gridcare_output()
    invalid = GridCareOutput(
        base.public_constraint_context,
        base.probabilistic_regional_risk,
        {**base.synthetic_flexibility_study, "capacity_claim": True},
        base.operator_confirmed_capacity,
    )
    with pytest.raises(ValueError, match="reject a capacity claim"):
        invalid.validate()
