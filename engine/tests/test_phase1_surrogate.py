from __future__ import annotations

import pytest

from capacity_backtest.phase1.surrogate import PhysicsOutcome, PhysicsSurrogate


def outcomes() -> list[PhysicsOutcome]:
    return [
        PhysicsOutcome(
            features={"load_factor": 0.5 + index * 0.02, "distance_km": 1 + index * 0.1},
            capacity_mw=100 - index,
            feasible=index < 15,
            binding_constraint="voltage" if index < 15 else "thermal",
        )
        for index in range(30)
    ]


def test_surrogate_screens_in_distribution_but_never_authorizes() -> None:
    surrogate = PhysicsSurrogate().fit(outcomes())
    result = surrogate.predict({"load_factor": 0.8, "distance_km": 2.5})
    assert result.status == "screened"
    assert result.approximate_capacity_mw is not None
    assert result.requires_detailed_verification
    assert surrogate.metadata()["automatic_capacity_authorized"] is False


def test_surrogate_abstains_out_of_distribution() -> None:
    result = PhysicsSurrogate().fit(outcomes()).predict(
        {"load_factor": 4.0, "distance_km": 2.5}
    )
    assert result.status == "abstained_ood"
    assert result.approximate_capacity_mw is None
    assert result.ood_features == ("load_factor",)


def test_surrogate_rejects_non_physics_training_and_small_samples() -> None:
    with pytest.raises(ValueError, match="at least 20"):
        PhysicsSurrogate().fit(outcomes()[:10])
    invalid = outcomes()
    invalid[0] = PhysicsOutcome(invalid[0].features, 100, True, "voltage", False)
    with pytest.raises(ValueError, match="physics-verified"):
        PhysicsSurrogate().fit(invalid)
