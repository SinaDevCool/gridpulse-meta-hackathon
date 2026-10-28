from __future__ import annotations

from dataclasses import replace

from capacity_backtest.contracts import TruthClass
from capacity_backtest.phase1.ac_envelope import OperatingState, run_ac_envelope_study
from capacity_backtest.phase1.capacity import build_capacity_assessment
from capacity_backtest.phase1.risk import backtest_risk_policies
from capacity_backtest.phase2.battery import BatteryConfig, BatteryRequest, simulate_battery
from capacity_backtest.phase2.capacity import build_dependable_capacity_assessment
from capacity_backtest.phase2.credibility import assess_portfolio_credibility
from capacity_backtest.phase2.fatigue import FatigueLimits, evaluate_fatigue
from capacity_backtest.phase2.phase_power import PhasePowerSpecification, validate_phase_power
from capacity_backtest.phase2.thermal_workload import (
    CoolingConfig,
    WorkloadConfig,
    simulate_cooling_workload,
)

from .test_phase0_domain import portfolio, provenance, scenario
from .test_phase1_ac import FakeProvider, model
from .test_phase1_risk import inputs
from .test_phase2_credibility import evidence


def phase1_assessment():
    forecast, envelope = inputs()
    ac = run_ac_envelope_study(
        model(), [OperatingState(stamp, 20) for stamp in envelope.timestamps], FakeProvider(),
        power_factor=0.96, truth_class=TruthClass.SYNTHETIC_BENCHMARK, envelope_id="p2-ac",
    )
    risk = backtest_risk_policies([48, 52, 53, 53, 54, 49], forecast, ac.envelope)
    return build_capacity_assessment(
        replace(scenario(), network_model_id="network-1"), ac, risk, provenance(),
        maximum_event_hours=4, annual_constrained_hours=120,
    )


def dependencies(*, terminal_target=5, complete_recovery=True):
    credibility = assess_portfolio_credibility(
        portfolio(), evidence("battery-1", 5, 5) + evidence("workload-1", 5, 5),
        assessed_at="2026-02-01T00:00:00+00:00", response_deadline_seconds=10,
    )
    fatigue = evaluate_fatigue([2, 2, 0, 0, 0, 0], 0.5, FatigueLimits(4, 6, 4, 100, 10, 1))
    phase = validate_phase_power(
        PhasePowerSpecification(
            {"a": 10, "b": 10, "c": 10}, {"a": 1, "b": 1, "c": 1},
            0.1, 0.95, -10, 10,
        )
    )
    battery = simulate_battery(
        BatteryConfig("battery-1", 10, 20, 15, 5, terminal_target, charge_efficiency=1, discharge_efficiency=1),
        [BatteryRequest("2026-01-01T00:00:00+00:00", 2), BatteryRequest("2026-01-01T01:00:00+00:00", -2)],
    )
    recovery = simulate_cooling_workload(
        [2, 0], [0, 4] if complete_recovery else [0, 0],
        CoolingConfig(8, 2, 2, maximum_thermal_debt_mwh=2, recovery_power_mw=2),
        WorkloadConfig(2, 2, 4),
    )
    return credibility, fatigue, phase, battery, recovery


def test_phase2_derates_conditional_capacity_to_dependable_contribution() -> None:
    credibility, fatigue, phase, battery, recovery = dependencies()
    result = build_dependable_capacity_assessment(
        phase1_assessment(), credibility, fatigue, phase, [battery], recovery
    )
    assert result.release_gate_passed
    assert result.non_delivery_reserve_mw > 0
    assert result.dependable_conditional_capacity_mw <= result.phase1.result.conditional_capacity_mw
    assert result.dependable_conditional_capacity_mw >= result.phase1.result.firm_capacity_mw
    assert result.phase1.result.capacity_claim is False


def test_phase2_fails_closed_for_terminal_soc_or_incomplete_recovery() -> None:
    credibility, fatigue, phase, battery, recovery = dependencies(
        terminal_target=20, complete_recovery=False
    )
    result = build_dependable_capacity_assessment(
        phase1_assessment(), credibility, fatigue, phase, [battery], recovery
    )
    assert not result.release_gate_passed
    assert set(result.blockers) >= {"battery_terminal_soc", "incomplete_recovery"}
