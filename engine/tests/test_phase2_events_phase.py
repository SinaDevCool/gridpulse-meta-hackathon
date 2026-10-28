from __future__ import annotations

import pytest

from capacity_backtest.phase2.events import (
    EnvelopeRegistration,
    EventKind,
    RecalculationEvent,
    RecalculationRegistry,
)
from capacity_backtest.phase2.phase_power import PhasePowerSpecification, validate_phase_power


def test_recalculation_registry_invalidates_only_matching_newer_material_events() -> None:
    registry = RecalculationRegistry()
    registry.register(
        EnvelopeRegistration(
            "result-1", "2026-01-01T00:00:00+00:00", "network-1", "bus-1",
            "forecast-1", ("battery-1",),
        )
    )
    registry.publish(
        RecalculationEvent(
            "old", EventKind.OUTAGE, "2025-12-31T00:00:00+00:00", network_model_id="network-1"
        )
    )
    registry.publish(
        RecalculationEvent(
            "other", EventKind.RESOURCE_UNAVAILABLE, "2026-01-02T00:00:00+00:00",
            resource_id="other-battery",
        )
    )
    registry.publish(
        RecalculationEvent(
            "soc", EventKind.SOC_DEVIATION, "2026-01-02T01:00:00+00:00",
            resource_id="battery-1",
        )
    )
    decision = registry.decision("result-1")
    assert decision.stale
    assert decision.reasons == ("soc_deviation:soc",)


def test_event_identity_is_immutable() -> None:
    registry = RecalculationRegistry()
    registry.publish(RecalculationEvent("e", EventKind.OUTAGE, "2026-01-01T00:00:00+00:00"))
    with pytest.raises(ValueError, match="immutable"):
        registry.publish(
            RecalculationEvent("e", EventKind.OUTAGE_REVISION, "2026-01-02T00:00:00+00:00")
        )


def test_balanced_reactive_power_passes_and_unbalanced_or_low_pf_fails() -> None:
    passed = validate_phase_power(
        PhasePowerSpecification(
            {"a": 10, "b": 10, "c": 10}, {"a": 1, "b": 1, "c": 1},
            0.1, 0.95, -10, 10,
        )
    )
    assert passed.passed
    failed = validate_phase_power(
        PhasePowerSpecification(
            {"a": 20, "b": 5, "c": 5}, {"a": 10, "b": 10, "c": 10},
            0.1, 0.95, -10, 10,
        )
    )
    assert not failed.passed
    assert set(failed.violations) == {"phase_unbalance", "minimum_power_factor", "reactive_capability"}
