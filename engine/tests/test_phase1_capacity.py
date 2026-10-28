from __future__ import annotations

from dataclasses import replace

from capacity_backtest.contracts import TruthClass
from capacity_backtest.phase1.ac_envelope import OperatingState, run_ac_envelope_study
from capacity_backtest.phase1.capacity import build_capacity_assessment
from capacity_backtest.phase1.risk import backtest_risk_policies

from .test_phase0_domain import provenance, scenario
from .test_phase1_ac import FakeProvider, model
from .test_phase1_risk import inputs


def test_phase1_builds_one_governed_capacity_envelope() -> None:
    forecast, envelope = inputs()
    states = [OperatingState(stamp, 20) for stamp in envelope.timestamps]
    ac = run_ac_envelope_study(
        model(), states, FakeProvider(), power_factor=0.96,
        truth_class=TruthClass.SYNTHETIC_BENCHMARK, envelope_id="phase1-ac",
    )
    risk = backtest_risk_policies([48, 52, 54, 58, 59, 49], forecast, ac.envelope)
    study_scenario = replace(scenario(), network_model_id="network-1")
    value = build_capacity_assessment(
        study_scenario, ac, risk, provenance(), maximum_event_hours=4,
        annual_constrained_hours=120,
    )
    assert value.result.capacity_claim is False
    assert value.result.firm_capacity_mw == 60
    assert value.result.conditional_capacity_mw >= value.result.firm_capacity_mw
    assert value.operating_conditions.required_resource_ids == ("battery-1", "workload-1")
    assert len(value.chronological_firm_envelope_mw) == 6
