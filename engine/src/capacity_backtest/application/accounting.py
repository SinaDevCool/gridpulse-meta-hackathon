"""Read-only pricing of an accepted schedule, never an optimisation or retail bill."""

from __future__ import annotations

from math import isfinite

from capacity_backtest.data_center.economics import integrate_energy_cost

from .experiments import _accepted_baseline
from .facility import ENGINE_VERSION, _fingerprint, parse_facility_plan_request

ACCOUNTING_REQUEST_SCHEMA = "gridpulse-facility-accounting-request-v1"
ACCOUNTING_RESULT_SCHEMA = "gridpulse-facility-accounting-result-v1"


def run_facility_accounting(payload: dict) -> dict:
    detailed = payload.get("schema_version") == "gridpulse-facility-accounting-request-v2"
    if (set(payload) - ({"tariff"} if detailed else set())) != {
        "schema_version",
        "facility_plan",
        "baseline",
        "prices_eur_per_mwh",
    } or payload["schema_version"] not in {
        ACCOUNTING_REQUEST_SCHEMA,
        "gridpulse-facility-accounting-request-v2",
    }:
        raise ValueError("unsupported accounting request")
    request, baseline = payload["facility_plan"], payload["baseline"]
    _accepted_baseline(request, baseline)
    parsed = parse_facility_plan_request(request)
    intervals = parsed["intervals"]
    prices = tuple(payload["prices_eur_per_mwh"])
    if len(intervals) > 100 or any(
        isinstance(value, bool) or not isinstance(value, (float, int)) for value in prices
    ):
        raise ValueError("invalid accounting prices or horizon")
    result = baseline["result"]
    actual = tuple(point["grid_import_mw"] for point in result["facility"]["points"])
    reference = tuple(point["grid_import_mw"] for point in result["baseline_facility"]["points"])
    energy = integrate_energy_cost(intervals, actual, (1.0,) * len(intervals))
    cost = integrate_energy_cost(intervals, actual, prices)
    baseline_cost = integrate_energy_cost(intervals, reference, prices)
    response = {
        "schema_version": ACCOUNTING_RESULT_SCHEMA,
        "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(payload),
        "baseline_result_fingerprint": baseline["result_fingerprint"],
        "grid_import_mwh": energy,
        "energy_cost_eur": cost,
        "baseline_energy_cost_eur": baseline_cost,
        "energy_cost_difference_eur": baseline_cost - cost,
        "basis": "fixed_schedule_energy_only",
        "excluded": [
            "demand_charges",
            "network_fees",
            "taxes",
            "export_credits",
            "battery_wear",
            "market_revenue",
        ],
        "automatic_live_dispatch_authorized": False,
    }
    if detailed:
        tariff = payload.get("tariff")
        fields = {
            "supplier_markup_eur_per_mwh",
            "network_energy_eur_per_mwh",
            "capacity_eur_per_kw_year",
            "prior_billing_peak_mw",
            "source",
            "reviewed_at",
        }
        if not isinstance(tariff, dict) or set(tariff) != fields:
            raise ValueError("Provide the complete reviewed tariff breakdown")
        for field in fields - {"source", "reviewed_at"}:
            value = tariff[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError("Invalid tariff component")
        from capacity_backtest.domain.base import parse_aware_timestamp

        parse_aware_timestamp(tariff["reviewed_at"], "tariff review")
        if (
            not isinstance(tariff["source"], str)
            or not tariff["source"].strip()
            or len(tariff["source"]) > 500
        ):
            raise ValueError("A tariff source is required")

        def breakdown(powers):
            mwh = integrate_energy_cost(intervals, powers, (1.0,) * len(intervals))
            energy_cost = integrate_energy_cost(intervals, powers, prices)
            markup = mwh * tariff["supplier_markup_eur_per_mwh"]
            network = mwh * tariff["network_energy_eur_per_mwh"]
            capacity = (
                max(0, max(powers) - tariff["prior_billing_peak_mw"])
                * 1000
                * tariff["capacity_eur_per_kw_year"]
            )
            return {
                "energy_eur": energy_cost,
                "supplier_markup_eur": markup,
                "network_energy_eur": network,
                "incremental_annual_capacity_eur": capacity,
                "total_eur": energy_cost + markup + network + capacity,
            }

        response.update(
            schema_version="gridpulse-facility-accounting-result-v2",
            basis="fixed_schedule_reviewed_tariff",
            plan_charges=breakdown(actual),
            baseline_charges=breakdown(reference),
            tariff=tariff,
            excluded=["taxes", "fixed_fees", "export_credits", "battery_wear", "market_revenue"],
            capacity_basis="incremental_annual_liability_above_prior_billing_peak_not_prorated_day_cost",
        )
    response["result_fingerprint"] = _fingerprint(response)
    return response
