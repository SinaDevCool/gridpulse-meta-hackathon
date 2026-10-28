import json
from datetime import datetime, timezone

import pytest

from capacity_backtest.adapters.capture import capture_read_only_payload
from capacity_backtest.adapters.price import parse_price_csv
from capacity_backtest.adapters.telemetry import parse_pcc_measurements
from capacity_backtest.storage import SnapshotStore, StorageLayout


def test_price_and_telemetry_adapters_are_strict_and_read_only(tmp_path) -> None:
    prices = parse_price_csv(b"timestamp,price_eur_per_mwh,market\n2026-01-01T00:00:00+00:00,10,day_ahead\n", source_id="price")
    assert prices[0].price_eur_per_mwh == 10
    telemetry = [{
        "measurement_id": "m", "pcc_id": "p", "timestamp": "2026-01-01T00:00:00+00:00",
        "sequence": 1, "voltage_kv": {"a": 20, "b": 20, "c": 20},
        "current_a": {"a": 1, "b": 1, "c": 1}, "active_power_mw": 1,
        "reactive_power_mvar": 0, "frequency_hz": 50, "quality": "valid",
    }]
    assert parse_pcc_measurements(json.dumps(telemetry).encode(), source_id="meter")[0].source == "meter"
    layout = StorageLayout(tmp_path / "repo", tmp_path / "data", tmp_path / "work", "local", None)
    capture = capture_read_only_payload(
        SnapshotStore(layout), source_id="price", publisher="test", source_url="https://example.invalid",
        content=b"x", extension="txt", retrieved_at=datetime.now(timezone.utc),
        truth_class="synthetic_demonstration", licence="test", adapter_version="v1",
    )
    assert capture.transport_mode == "read_only" and not capture.command_capable


def test_adapter_schema_drift_fails_closed() -> None:
    with pytest.raises(ValueError, match="schema drift"):
        parse_price_csv(b"time,value\nx,1\n", source_id="bad")
