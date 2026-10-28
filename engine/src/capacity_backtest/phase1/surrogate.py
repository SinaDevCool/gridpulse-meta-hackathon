"""Physics-only surrogate screening with strict out-of-distribution abstention."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import (  # type: ignore[import-untyped]
    RandomForestClassifier,
    RandomForestRegressor,
)


@dataclass(frozen=True)
class PhysicsOutcome:
    features: dict[str, float]
    capacity_mw: float
    feasible: bool
    binding_constraint: str
    physics_verified: bool = True

    def validate(self) -> None:
        if not self.physics_verified:
            raise ValueError("surrogates may train only on physics-verified outcomes")
        if not self.features or any(not np.isfinite(value) for value in self.features.values()):
            raise ValueError("physics features must be finite and non-empty")
        if self.capacity_mw < 0 or not self.binding_constraint:
            raise ValueError("physics outcomes require non-negative capacity and a constraint")


@dataclass(frozen=True)
class SurrogatePrediction:
    status: str
    approximate_capacity_mw: float | None
    feasible_probability: float | None
    binding_constraint: str | None
    requires_detailed_verification: bool
    ood_features: tuple[str, ...]


class PhysicsSurrogate:
    """Screen and prioritize AC cases; never authorize a capacity result."""

    def __init__(self, *, random_state: int = 17, ood_tolerance_fraction: float = 0.05):
        if ood_tolerance_fraction < 0:
            raise ValueError("OOD tolerance cannot be negative")
        self.random_state = random_state
        self.ood_tolerance_fraction = ood_tolerance_fraction
        self.feature_names: tuple[str, ...] = ()
        self.bounds: dict[str, tuple[float, float]] = {}
        self._capacity: RandomForestRegressor | None = None
        self._feasible: RandomForestClassifier | None = None
        self._constraint: RandomForestClassifier | None = None

    def fit(self, outcomes: list[PhysicsOutcome]) -> PhysicsSurrogate:
        if len(outcomes) < 20:
            raise ValueError("physics surrogate requires at least 20 verified outcomes")
        for outcome in outcomes:
            outcome.validate()
        names = tuple(sorted(outcomes[0].features))
        if any(tuple(sorted(item.features)) != names for item in outcomes):
            raise ValueError("physics outcomes must share one feature schema")
        x = np.asarray([[item.features[name] for name in names] for item in outcomes], dtype=float)
        self.feature_names = names
        self.bounds = {
            name: (float(x[:, index].min()), float(x[:, index].max()))
            for index, name in enumerate(names)
        }
        self._capacity = RandomForestRegressor(
            n_estimators=200, max_depth=8, min_samples_leaf=2, random_state=self.random_state, n_jobs=1
        ).fit(x, [item.capacity_mw for item in outcomes])
        self._feasible = RandomForestClassifier(
            n_estimators=200, max_depth=8, min_samples_leaf=2, random_state=self.random_state, n_jobs=1
        ).fit(x, [item.feasible for item in outcomes])
        self._constraint = RandomForestClassifier(
            n_estimators=200, max_depth=8, min_samples_leaf=2, random_state=self.random_state, n_jobs=1
        ).fit(x, [item.binding_constraint for item in outcomes])
        return self

    def predict(self, features: dict[str, float]) -> SurrogatePrediction:
        if self._capacity is None or self._feasible is None or self._constraint is None:
            raise RuntimeError("physics surrogate has not been fitted")
        if tuple(sorted(features)) != self.feature_names:
            raise ValueError("surrogate feature schema mismatch")
        ood = []
        for name in self.feature_names:
            low, high = self.bounds[name]
            width = max(high - low, 1e-9)
            tolerance = width * self.ood_tolerance_fraction
            if not low - tolerance <= features[name] <= high + tolerance:
                ood.append(name)
        if ood:
            return SurrogatePrediction("abstained_ood", None, None, None, True, tuple(ood))
        x = np.asarray([[features[name] for name in self.feature_names]], dtype=float)
        classes = list(self._feasible.classes_)
        probabilities = self._feasible.predict_proba(x)[0]
        feasible_probability = (
            float(probabilities[classes.index(True)]) if True in classes else float(classes[0] is True)
        )
        return SurrogatePrediction(
            status="screened",
            approximate_capacity_mw=max(0.0, float(self._capacity.predict(x)[0])),
            feasible_probability=feasible_probability,
            binding_constraint=str(self._constraint.predict(x)[0]),
            requires_detailed_verification=True,
            ood_features=(),
        )

    def metadata(self) -> dict[str, Any]:
        if not self.feature_names:
            raise RuntimeError("physics surrogate has not been fitted")
        return {
            "schema_version": "gridpulse-physics-surrogate-v1",
            "training_source": "physics_verified_only",
            "feature_names": list(self.feature_names),
            "bounds": self.bounds,
            "automatic_capacity_authorized": False,
            "requires_detailed_verification": True,
        }
