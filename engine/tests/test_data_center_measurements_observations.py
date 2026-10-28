from capacity_backtest.contracts import TruthClass
from capacity_backtest.data_center.measurement_boundaries import (
    FacilityEnergyBoundary,
    MeasuredComponent,
    MeteringPoint,
    assess_energy_balance,
)
from capacity_backtest.data_center.observations import ComponentObservation, align_observations


def point(component=MeasuredComponent.PCC):
    return MeteringPoint("m", "f", component, "incoming", "MW", 900, "meter", "0.2S", None, None, "2026-01-01T00:00:00+00:00", TruthClass.SYNTHETIC_DEMONSTRATION)


def observation(sequence=1, available="2026-01-01T00:01:00+00:00"):
    return ComponentObservation("o", "m", MeasuredComponent.PCC, "2026-01-01T00:00:00+00:00", available, available, sequence, 1.0, "MW", "valid", "meter", "a" * 64)


def test_boundaries_and_energy_balance_are_explicit() -> None:
    FacilityEnergyBoundary("f", (point(),), (MeasuredComponent.COOLING,)).validate()
    assert assess_energy_balance(supplied_mwh=100, consumed_mwh=99.5).passed
    assert not assess_energy_balance(supplied_mwh=100, consumed_mwh=95).passed


def test_alignment_excludes_future_revisions_and_reports_quality() -> None:
    aligned, quality = align_observations(
        (observation(), observation(2, "2026-01-03T00:00:00+00:00")),
        planning_cutoff="2026-01-02T00:00:00+00:00", expected_measurement_ids=("m",),
        interval_timestamps=("2026-01-01T00:00:00+00:00",),
    )
    assert aligned[("m", "2026-01-01T00:00:00+00:00")].sequence == 1
    assert quality.future_leakage_count == 1


from dataclasses import replace

import pytest

from capacity_backtest.data_center.contracts import PlanningInterval
from capacity_backtest.data_center.observations import aggregate_observations


def test_interval_aggregation_conserves_energy_and_never_zero_fills_gaps():
    interval = (PlanningInterval(0, "2026-01-01T00:00:00Z", 15),)
    kwargs = {"planning_cutoff": "2026-01-02T00:00:00Z"}
    result, = aggregate_observations((observation(),), point(), interval, **kwargs)
    assert result.energy_mwh == 0.25 and result.mean_power_mw == 1
    assert result.coverage_fraction == 1 and not result.blockers
    missing, = aggregate_observations((observation(),), point(), interval, maximum_gap_seconds=300, **kwargs)
    assert missing.energy_mwh is None and missing.mean_power_mw is None
    assert missing.coverage_fraction == pytest.approx(1 / 3)
    assert "incomplete_interval" in missing.blockers


def test_counter_aggregation_rejects_resets_and_respects_cutoff():
    meter = replace(point(), unit="kWh", sample_kind="cumulative_energy")
    first = replace(observation(), value=100, unit="kWh")
    second = replace(first, observation_id="o2", event_at="2026-01-01T00:15:00Z",
                     available_at="2026-01-01T00:15:00Z", ingested_at="2026-01-01T00:15:00Z", value=350)
    interval = (PlanningInterval(0, first.event_at, 15),)
    result, = aggregate_observations((first, second), meter, interval, planning_cutoff="2026-01-02T00:00:00Z")
    assert result.energy_mwh == 0.25 and len(result.source_observation_ids) == 2
    reset, = aggregate_observations((first, replace(second, value=10)), meter, interval, planning_cutoff="2026-01-02T00:00:00Z")
    assert reset.energy_mwh is None and "counter_reset" in reset.blockers
    future, = aggregate_observations((first, second), meter, interval, planning_cutoff="2026-01-01T00:10:00Z")
    assert future.energy_mwh is None


def test_interval_averages_cannot_silently_overlap_and_sign_is_explicit():
    interval = (PlanningInterval(0, "2026-01-01T00:00:00Z", 15),)
    cutoff = "2026-01-02T00:00:00Z"
    signed, = aggregate_observations((observation(),), replace(point(), sign_multiplier=-1), interval, planning_cutoff=cutoff)
    assert signed.energy_mwh == -.25
    following = replace(observation(), observation_id="o2", event_at="2026-01-01T00:05:00Z",
                        available_at="2026-01-01T00:05:00Z", ingested_at="2026-01-01T00:05:00Z")
    available = "2026-01-01T00:20:00Z"
    with pytest.raises(ValueError, match="overlap"):
        aggregate_observations(tuple(replace(row, available_at=available, ingested_at=available) for row in (observation(), following)), replace(point(), sample_kind="interval_average"), interval, planning_cutoff=cutoff)


def test_aggregation_never_treats_future_held_values_or_unfinished_averages_as_measurements():
    interval = (PlanningInterval(0, "2026-01-01T00:00:00Z", 15),)
    result, = aggregate_observations((observation(),), point(), interval, planning_cutoff="2026-01-01T00:05:00Z")
    assert result.energy_mwh is None and result.coverage_fraction == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="available"):
        aggregate_observations((observation(),), replace(point(), sample_kind="interval_average"), interval, planning_cutoff="2026-01-02T00:00:00Z")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_observations_and_balances_are_rejected(value):
    with pytest.raises(ValueError):
        replace(observation(), value=value).validate()
    with pytest.raises(ValueError):
        assess_energy_balance(supplied_mwh=value, consumed_mwh=1)


def test_alignment_normalizes_equivalent_instants_and_rejects_duplicate_axes():
    args = {"planning_cutoff": "2026-01-02T00:00:00Z", "expected_measurement_ids": ("m",),
                "interval_timestamps": ("2026-01-01T01:00:00+01:00",)}
    aligned, quality = align_observations((observation(),), **args)
    assert quality.accepted and quality.completeness_fraction == 1
    assert ("m", args["interval_timestamps"][0]) in aligned
    with pytest.raises(ValueError, match="unique"):
        align_observations((), **{**args, "expected_measurement_ids": ("m", "m")})
    with pytest.raises(ValueError):
        align_observations((), **args, minimum_completeness_fraction=float("nan"))
    with pytest.raises(ValueError):
        replace(observation(), unit="degrees C").validate()
