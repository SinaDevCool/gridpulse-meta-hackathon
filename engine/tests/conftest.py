"""Architectural test-suite classification for resumable verification."""

from __future__ import annotations

from pathlib import Path

import pytest

PRIMARY_MARKERS = ("core", "capacity", "planning", "market", "shadow", "territory", "legacy")

MARKER_FILES = {
    "planning": {
        "test_facility_experiments.py", "test_facility_accounting.py",
        "test_physics_artifacts.py",
        "test_data_center_calibration.py",
        "test_data_center_measurements_observations.py",
        "test_data_center_pilot_readiness.py",
        "test_data_center_planner_fallback.py",
        "test_workload_adapter_calibration.py",
    },
    "market": {
        "test_data_center_backtest_economics.py",
        "test_market_products.py",
    },
    "shadow": {
        "test_data_center_reporting.py",
        "test_data_center_shadow.py",
        "test_data_center_verification.py",
        "test_adapter_safety_telemetry_quality.py",
        "test_data_center_shadow_monitor.py",
        "test_delivery_calibration_governance.py",
        "test_read_only_adapters.py",
        "test_shadow_reporting_security.py",
    },
}

CORE_FILES = {
    "test_evidence_pipeline.py", "test_events.py", "test_network_contracts.py",
    "test_phase0_domain.py", "test_storage.py", "test_validation.py",
}

CAPACITY_PREFIXES = (
    "test_capacity_", "test_phase0_pipeline", "test_phase1_", "test_phase2_",
    "test_flexibility_requirement", "test_network_", "test_contingency_",
    "test_cgmes", "test_hourly_ac", "test_optimized_deflex", "test_deflex",
)

PLANNING_PREFIXES = ("test_data_center_",)

TERRITORY_PREFIXES = (
    "test_territory_", "test_regional_", "test_fifty_hertz_", "test_dwd",
    "test_entsoe", "test_open_sources", "test_scenario_coupling",
)

SLOW_FILES = {
    "test_capacity_real_public.py", "test_capacity_study_pipeline_integration.py",
    "test_network_study.py", "test_research_pipeline.py",
}

CAPACITY_CONTRACT_FILES = {
    "test_capacity_ownership.py", "test_capacity_readiness.py",
    "test_flexibility_requirement.py", "test_network_contracts.py",
    "test_phase0_domain.py", "test_phase1_capacity.py", "test_phase2_capacity.py",
    "test_phase2_credibility.py", "test_phase2_events_phase.py",
}

CAPACITY_PHYSICS_PREFIXES = (
    "test_network_", "test_contingency_", "test_cgmes", "test_hourly_ac",
    "test_deflex", "test_optimized_deflex", "test_phase1_ac", "test_phase2_battery",
    "test_phase2_thermal", "test_phase2_events_phase",
)


def _primary_marker(filename: str) -> str:
    for marker, files in MARKER_FILES.items():
        if filename in files:
            return marker
    if filename in CORE_FILES:
        return "core"
    if filename.startswith(CAPACITY_PREFIXES):
        return "capacity"
    if filename.startswith(PLANNING_PREFIXES):
        return "planning"
    if filename.startswith("test_phase3_"):
        return "shadow"
    if filename.startswith(TERRITORY_PREFIXES):
        return "territory"
    return "legacy"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Explicitly enable slow integration tests (disabled by default).",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    run_slow = bool(items[0].config.getoption("--run-slow")) if items else False
    slow_disabled = pytest.mark.skip(reason="slow test requires explicit --run-slow")
    for item in items:
        filename = Path(str(item.fspath)).name
        existing = [name for name in PRIMARY_MARKERS if item.get_closest_marker(name)]
        if len(existing) > 1:
            raise pytest.UsageError(f"{item.nodeid} has multiple architectural markers: {existing}")
        if not existing:
            primary = _primary_marker(filename)
            item.add_marker(getattr(pytest.mark, primary))
        else:
            primary = existing[0]
        if primary == "capacity":
            if filename in CAPACITY_CONTRACT_FILES:
                item.add_marker(pytest.mark.capacity_contract)
            elif filename.startswith(CAPACITY_PHYSICS_PREFIXES):
                item.add_marker(pytest.mark.capacity_physics)
            else:
                item.add_marker(pytest.mark.capacity_pipeline)
        if primary == "territory":
            marker = (
                "territory_resolution"
                if filename.startswith("test_territory_")
                else "territory_sources"
            )
            item.add_marker(getattr(pytest.mark, marker))
        if filename in SLOW_FILES:
            item.add_marker(pytest.mark.slow)
            if not run_slow:
                item.add_marker(slow_disabled)
