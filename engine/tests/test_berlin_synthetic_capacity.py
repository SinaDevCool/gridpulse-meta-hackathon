from grid_data.berlin_synthetic_capacity import (
    SLACK_NODE_ID,
    build_berlin_synthetic_model,
)


def test_berlin_model_is_meshed_and_explicitly_synthetic():
    model = build_berlin_synthetic_model()

    assert len(model.buses) == 16
    assert len(model.branches) >= len(model.buses)
    assert len(model.contingencies) == len(model.branches)
    assert model.provenance["evidence_class"] == "synthetic_geographic_demonstration"
    assert model.validation_class == "synthetic_demonstration"
    assert [item["bus"] for item in model.generators if item.get("slack")] == [SLACK_NODE_ID]
