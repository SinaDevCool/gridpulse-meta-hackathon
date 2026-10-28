from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest

from capacity_backtest.phase2.battery import BatteryConfig, BatteryRequest, simulate_battery

GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_phase2_cases.json").read_text(encoding="utf-8")
)["battery"]


def config(**changes) -> BatteryConfig:
    values = {
        "resource_id": "battery-1",
        "rated_power_mw": GOLDEN["rated_power_mw"],
        "rated_energy_mwh": GOLDEN["rated_energy_mwh"],
        "initial_soc_mwh": GOLDEN["initial_soc_mwh"],
        "minimum_reserve_mwh": GOLDEN["minimum_reserve_mwh"],
        "terminal_target_mwh": 5,
        "discharge_efficiency": 1,
        "charge_efficiency": 1,
        "soc_uncertainty_mwh": GOLDEN["soc_uncertainty_mwh"],
    }
    values.update(changes)
    return BatteryConfig(**values)


def test_battery_respects_reserve_and_soc_uncertainty() -> None:
    trajectory = simulate_battery(
        config(),
        [
            BatteryRequest("2026-01-01T00:00:00+00:00", GOLDEN["first_request_mw"]),
            BatteryRequest("2026-01-01T01:00:00+00:00", 10),
        ],
    )
    assert trajectory.points[0].delivered_power_mw == GOLDEN["expected_first_delivery_mw"]
    assert trajectory.points[1].delivered_power_mw == 0
    assert trajectory.ending_soc_mwh == 6


def test_battery_models_temperature_unavailability_degradation_and_terminal_target() -> None:
    trajectory = simulate_battery(
        config(degradation_fraction=0.1, unavailable_hours=(1,), terminal_target_mwh=10),
        [
            BatteryRequest("2026-01-01T00:00:00+00:00", 10, temperature_c=-5),
            BatteryRequest("2026-01-01T01:00:00+00:00", 5),
        ],
    )
    assert trajectory.points[0].available_power_mw < 10
    assert trajectory.points[1].availability is False
    assert trajectory.shortfall_mwh > 0
    assert trajectory.terminal_target_met is False


def test_quarter_hour_replay_preserves_fixed_hourly_energy_and_efficiency() -> None:
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    asset = config(initial_soc_mwh=15, minimum_reserve_mwh=1, soc_uncertainty_mwh=0,
                   terminal_target_mwh=1, charge_efficiency=.95, discharge_efficiency=.9)
    hourly = [BatteryRequest((origin + timedelta(hours=i)).isoformat(), power)
              for i, power in enumerate([2, -2])]
    quarters = [BatteryRequest((origin + timedelta(minutes=i * 15)).isoformat(), power)
                for i, power in enumerate([2] * 4 + [-2] * 4)]
    coarse = simulate_battery(asset, hourly, interval_hours=1)
    fine = simulate_battery(asset, quarters, interval_hours=.25)
    assert fine.ending_soc_mwh == pytest.approx(coarse.ending_soc_mwh)
    assert fine.ending_soc_mwh == pytest.approx(15 - 2 / .9 + 2 * .95)
