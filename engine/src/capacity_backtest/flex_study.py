"""Couple bounded flexibility dispatch to synthetic AC benchmark envelopes."""

from __future__ import annotations

import math
from collections import defaultdict

from grid_data.deflex import FlexibilityPolicy, dispatch_flexibility

from .backtest import BenchmarkRecord

SITE_SCENARIOS_MW = (10.0, 25.0, 50.0, 100.0, 200.0)


def hourly_synthetic_profiles(
    site_mw: float, n0_mw: float, n1_mw: float, operating_scenario: str
) -> tuple[list[float], list[float], list[float]]:
    """Deterministic reference profiles; never represented as measured regional loading."""
    stress = {
        "annual_minimum": 0.92,
        "annual_median": 1.0,
        "summer_peak": 1.08,
        "winter_peak": 1.12,
    }.get(operating_scenario, 1.0)
    demand, n0, n1 = [], [], []
    for hour in range(8760):
        hour_of_day = hour % 24
        day = hour // 24
        daily = 0.5 + 0.5 * math.sin(2 * math.pi * (hour_of_day - 8) / 24)
        seasonal = 0.5 + 0.5 * math.cos(2 * math.pi * (day - 15) / 365)
        # A continuous 80% critical floor plus a bounded shiftable workload pattern.
        demand.append(site_mw * (0.80 + 0.20 * daily))
        derating = min(0.18, 0.04 * daily + 0.06 * seasonal) * stress
        n0.append(max(0.0, n0_mw * (1 - derating)))
        n1.append(max(0.0, n1_mw * (1 - derating * 1.15)))
    return demand, n0, n1


def run_synthetic_flexibility_study(records: list[BenchmarkRecord]) -> dict[str, object]:
    paired: dict[tuple[str, str, str], dict[str, BenchmarkRecord]] = defaultdict(dict)
    for record in records:
        paired[(record.network_id, record.node_id, record.scenario)][record.security_case] = record
    results = []
    for (network_id, node_id, operating_scenario), security in sorted(paired.items()):
        if set(security) != {"n_0", "n_1"}:
            continue
        n0 = security["n_0"].truth_capacity_mw
        n1 = security["n_1"].truth_capacity_mw
        for site_mw in SITE_SCENARIOS_MW:
            policy = FlexibilityPolicy(
                interruptible_fraction=0.10,
                maximum_interruption_hours=4,
                annual_constrained_hour_budget=120,
                recovery_hours=4,
                battery_power_mw=site_mw * 0.25,
                battery_energy_mwh=site_mw,
                minimum_reserve_soc_fraction=0.10,
                ramp_limit_mw_per_hour=site_mw * 0.5,
            )
            demand_profile, n0_profile, n1_profile = hourly_synthetic_profiles(
                site_mw, n0, n1, operating_scenario
            )
            dispatch = dispatch_flexibility(demand_profile, n0_profile, n1_profile, policy)
            dispatch.pop("trace")
            results.append(
                {
                    "network_id": network_id,
                    "node_id": node_id,
                    "operating_scenario": operating_scenario,
                    "site_load_mw": site_mw,
                    "n0_binding_constraint": security["n_0"].binding_constraint,
                    "n1_binding_constraint": security["n_1"].binding_constraint,
                    **dispatch,
                }
            )
    uncertainty = []
    for site_mw in SITE_SCENARIOS_MW:
        selected = [item for item in results if item["site_load_mw"] == site_mw]
        uncertainty.append(
            {
                "site_load_mw": site_mw,
                "cases": len(selected),
                "constrained_hours_min": min(item["constrained_hours"] for item in selected),
                "constrained_hours_max": max(item["constrained_hours"] for item in selected),
                "unserved_mwh_min": min(item["unserved_mwh"] for item in selected),
                "unserved_mwh_max": max(item["unserved_mwh"] for item in selected),
            }
        )
    return {
        "classification": "synthetic_benchmark",
        "capacity_claim": False,
        "method": "hourly bounded dispatch against time-varying synthetic AC N-0/N-1 envelopes",
        "profile_origin": "deterministic reference-inspired scenario; not measured regional loading",
        "site_scenarios_mw": list(SITE_SCENARIOS_MW),
        "uncertainty_by_site_load": uncertainty,
        "results": results,
    }
