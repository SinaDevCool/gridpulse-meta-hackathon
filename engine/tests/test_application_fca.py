from datetime import datetime, timedelta, timezone

from capacity_backtest.application import FCA_INTERVAL_REQUEST_SCHEMA, run_fca_interval


def request(loads: list[float]) -> dict[str, object]:
    return {
        "schema_version": FCA_INTERVAL_REQUEST_SCHEMA,
        "points": [
            {"timestamp": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index * 15)).isoformat(), "import_mw": load, "export_mw": 0}
            for index, load in enumerate(loads)
        ],
        "settings": {
            "firm_import_mw": 50, "conditional_import_mw": 0,
            "minimum_critical_load_mw": 40, "shiftable_load_mw": 5,
            "battery_power_mw": 10, "battery_energy_mwh": 5,
            "battery_round_trip_efficiency": 1, "battery_minimum_soc": 0,
            "initial_battery_soc": 1, "energy_value_eur_mwh": 200,
            "battery_degradation_eur_mwh": 20,
        },
    }


def test_fca_uses_workload_before_battery_and_is_deterministic() -> None:
    first = run_fca_interval(request([60]))
    assert first == run_fca_interval(request([60]))
    point = first["result"]["timeline"][0]
    assert point["workload_response_mw"] == 5
    assert point["battery_response_mw"] == 5
    assert first["result"]["residual_unserved_mwh"] == 0
    assert first["capacity_claim"] is False


def test_fca_tracks_restriction_events_and_battery_exhaustion() -> None:
    result = run_fca_interval(request([70] * 8))["result"]
    assert result["restriction_events"] == 1
    assert result["longest_restriction_hours"] == 2
    assert result["battery_discharge_mwh"] == 5
    assert result["residual_unserved_mwh"] > 0


def test_fca_rejects_missing_intervals() -> None:
    payload = request([50, 50, 50])
    payload["points"][2]["timestamp"] = "2026-01-01T01:00:00+00:00"
    try:
        run_fca_interval(payload)
    except ValueError as error:
        assert "inconsistent" in str(error)
    else:
        raise AssertionError("missing intervals must fail closed")
