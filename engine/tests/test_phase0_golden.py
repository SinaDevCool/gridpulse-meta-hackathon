from __future__ import annotations

import json
from pathlib import Path

from grid_data.deflex import FlexibilityPolicy, dispatch_flexibility

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_phase0_cases.json").read_text(encoding="utf-8")
)["cases"]


def test_golden_network_safety_cases() -> None:
    for case in CASES[:3]:
        safe = all(
            demand <= min(n0, n1)
            for demand, n0, n1 in zip(case["demand_mw"], case["n0_mw"], case["n1_mw"])
        )
        assert safe is case["expected_safe"], case["id"]


def test_golden_energy_limited_battery_case() -> None:
    case = next(item for item in CASES if item["id"] == "energy_limited_battery")
    policy = FlexibilityPolicy(
        interruptible_fraction=0,
        maximum_interruption_hours=1,
        annual_constrained_hour_budget=0,
        recovery_hours=1,
        battery_power_mw=case["battery_power_mw"],
        battery_energy_mwh=case["battery_energy_mwh"],
        charge_efficiency=1,
        discharge_efficiency=1,
        minimum_reserve_soc_fraction=0,
        ramp_limit_mw_per_hour=None,
        critical_load_fraction=1,
        workload_deadline_hours=1,
        battery_degradation_cost_per_mwh=0,
    )
    result = dispatch_flexibility(case["demand_mw"], case["n0_mw"], case["n1_mw"], policy)
    assert result["unserved_mwh"] == case["expected_unserved_mwh"]
