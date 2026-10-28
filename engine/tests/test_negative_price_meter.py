from dataclasses import replace

import pytest

from capacity_backtest.data_center.optimizer import optimize_facility_flexibility
from capacity_backtest.data_center.economics import EconomicTariff
from .test_data_center_optimizer import inputs


def test_replay_tariff_accepts_negative_energy_but_not_invalid_charges():
    tariff = EconomicTariff((-10.0, 20.0), 0, 0, 0, 0)
    tariff.validate(2)
    with pytest.raises(ValueError):
        replace(tariff, demand_charge_eur_per_mw=-1).validate(2)
    with pytest.raises(ValueError):
        replace(tariff, energy_price_eur_per_mwh=(float("nan"), 20)).validate(2)


def test_negative_prices_pay_only_for_physical_imports():
    values = inputs(required=0)
    values["economics"] = replace(values["economics"], import_price_eur_per_mwh=(-100.0,)*4)
    result = optimize_facility_flexibility(**values)
    assert result.status == "optimal", result.diagnostics
    assert result.assessment.feasible
    actual_cost = sum(point.grid_import_mw * -100 for point in result.facility.points)
    assert result.objective_eur == pytest.approx(actual_cost, abs=1e-6)
    assert max(point.grid_import_mw for point in result.facility.points) < values["facility"].import_limit_mw


def test_surplus_generation_never_creates_negative_price_import_revenue():
    values = inputs(required=0)
    values["economics"] = replace(values["economics"], import_price_eur_per_mwh=(-100.0,)*4)
    result = optimize_facility_flexibility(**values, onsite_generation_mw=(10.0,)*4)
    assert result.status == "optimal"
    assert all(point.grid_import_mw == 0 for point in result.facility.points)
    assert result.objective_eur == pytest.approx(0, abs=1e-6)
