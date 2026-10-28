from pathlib import Path

from capacity_backtest.adapters.safety import assess_adapter_safety
from capacity_backtest.data_center.telemetry_quality import assess_component_telemetry

from .test_data_center_measurements_observations import observation


def test_adapter_package_has_no_command_or_write_transport_path() -> None:
    root = Path(__file__).parents[1] / "src" / "capacity_backtest" / "adapters"
    result = assess_adapter_safety(root)
    assert result.passed and result.inspected_files >= 4


def test_cross_channel_telemetry_quality_is_fail_closed() -> None:
    good = assess_component_telemetry(
        (observation(),), reference_times=("2026-01-01T00:00:00+00:00",),
        supplied_energy_mwh=1, consumed_energy_mwh=1,
    )
    assert good.accepted
    bad = assess_component_telemetry(
        (observation(),), reference_times=("2026-01-01T00:00:10+00:00",),
        supplied_energy_mwh=1, consumed_energy_mwh=0.8,
    )
    assert set(bad.blockers) == {"clock_offset", "energy_balance"}
