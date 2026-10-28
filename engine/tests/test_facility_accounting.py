from copy import deepcopy

import pytest

from capacity_backtest.application.accounting import run_facility_accounting
from capacity_backtest.application.facility import run_facility_plan

from .test_application_facility import request


def test_accounting_prices_existing_plan_and_rejects_tampering():
    model = request()
    baseline = run_facility_plan(model)
    payload = {
        "schema_version": "gridpulse-facility-accounting-request-v1",
        "facility_plan": model,
        "baseline": baseline,
        "prices_eur_per_mwh": [100] * len(model["intervals"]),
    }
    result = run_facility_accounting(payload)
    assert result["energy_cost_eur"] == pytest.approx(result["grid_import_mwh"] * 100)
    assert result["baseline_result_fingerprint"] == baseline["result_fingerprint"]
    assert not result["automatic_live_dispatch_authorized"]
    bad = deepcopy(payload)
    bad["baseline"]["result_fingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        run_facility_accounting(bad)
    with pytest.raises(ValueError):
        run_facility_accounting(
            {**payload, "prices_eur_per_mwh": [float("nan")] * len(model["intervals"])}
        )


def test_negative_interval_prices_are_integrated_without_rescheduling():
    model = request()
    baseline = run_facility_plan(model)
    original = deepcopy(baseline)
    prices = [-25, 0, 100, 50]
    result = run_facility_accounting(
        {
            "schema_version": "gridpulse-facility-accounting-request-v1",
            "facility_plan": model,
            "baseline": baseline,
            "prices_eur_per_mwh": prices,
        }
    )
    expected = sum(
        point["grid_import_mw"] * interval["duration_minutes"] / 60 * price
        for point, interval, price in zip(
            baseline["result"]["facility"]["points"], model["intervals"], prices
        )
    )
    assert result["energy_cost_eur"] == pytest.approx(expected)
    assert baseline == original


def test_reviewed_tariff_preserves_negative_energy_and_annual_capacity_basis():
    model = request()
    baseline = run_facility_plan(model)
    tariff = {
        "supplier_markup_eur_per_mwh": 2,
        "network_energy_eur_per_mwh": 3,
        "capacity_eur_per_kw_year": 40,
        "prior_billing_peak_mw": 0,
        "source": "Reviewed test contract",
        "reviewed_at": "2026-10-27T00:00:00Z",
    }
    payload = {
        "schema_version": "gridpulse-facility-accounting-request-v2",
        "facility_plan": model,
        "baseline": baseline,
        "prices_eur_per_mwh": [-25] * len(model["intervals"]),
        "tariff": tariff,
    }
    result = run_facility_accounting(payload)
    charges = result["plan_charges"]
    assert result["schema_version"].endswith("v2")
    assert charges["energy_eur"] == pytest.approx(-25 * result["grid_import_mwh"])
    assert charges["network_energy_eur"] == pytest.approx(3 * result["grid_import_mwh"])
    peak = max(p["grid_import_mw"] for p in baseline["result"]["facility"]["points"])
    assert charges["incremental_annual_capacity_eur"] == pytest.approx(peak * 1000 * 40)
    with pytest.raises(ValueError):
        run_facility_accounting({**payload, "tariff": {**tariff, "capacity_eur_per_kw_year": -1}})
    with pytest.raises(ValueError):
        run_facility_accounting(
            {**payload, "schema_version": "gridpulse-facility-accounting-request-v1"}
        )


def test_prior_peak_removes_incremental_capacity_liability():
    model = request()
    baseline = run_facility_plan(model)
    tariff = {
        "supplier_markup_eur_per_mwh": 0,
        "network_energy_eur_per_mwh": 0,
        "capacity_eur_per_kw_year": 40,
        "prior_billing_peak_mw": 100,
        "source": "Reviewed contract",
        "reviewed_at": "2026-10-27T00:00:00Z",
    }
    result = run_facility_accounting(
        {
            "schema_version": "gridpulse-facility-accounting-request-v2",
            "facility_plan": model,
            "baseline": baseline,
            "prices_eur_per_mwh": [-10] * len(model["intervals"]),
            "tariff": tariff,
        }
    )
    assert result["plan_charges"]["incremental_annual_capacity_eur"] == 0
