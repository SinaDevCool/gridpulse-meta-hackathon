from __future__ import annotations

from dataclasses import replace

from capacity_backtest.contracts import TruthClass
from capacity_backtest.phase2.capacity import build_dependable_capacity_assessment
from capacity_backtest.phase3.readiness import assess_operational_readiness

from .test_phase2_capacity import dependencies, phase1_assessment


def dependable():
    credibility, fatigue, phase, battery, recovery = dependencies()
    return build_dependable_capacity_assessment(
        phase1_assessment(), credibility, fatigue, phase, [battery], recovery
    )


def test_digital_twin_readiness_does_not_imply_live_authorization() -> None:
    result = assess_operational_readiness(
        dependable(), telemetry_configured=True, command_channel_configured=True,
        acknowledgement_supported=True, fail_safe_tested=True,
        delivery_verification_configured=True,
    )
    assert result.ready_for_digital_twin_dispatch
    assert not result.live_dispatch_authorized
    assert set(result.blockers) == {
        "operator_dispatch_authorization_missing", "operator_confirmed_capacity_missing"
    }


def test_live_readiness_requires_every_gate_and_explicit_authorization() -> None:
    synthetic = dependable()
    operator_result = replace(
        synthetic.phase1.result,
        truth_class=TruthClass.OPERATOR_CONFIRMED,
        capacity_claim=True,
    )
    operator_phase1 = replace(synthetic.phase1, result=operator_result)
    operator_capacity = replace(synthetic, phase1=operator_phase1)
    ready = assess_operational_readiness(
        operator_capacity, telemetry_configured=True, command_channel_configured=True,
        acknowledgement_supported=True, fail_safe_tested=True,
        delivery_verification_configured=True, operator_authorization_id="operator-auth-1",
    )
    assert ready.live_dispatch_authorized
    assert not ready.blockers
    blocked = assess_operational_readiness(
        dependable(), telemetry_configured=False, command_channel_configured=True,
        acknowledgement_supported=True, fail_safe_tested=False,
        delivery_verification_configured=True, operator_authorization_id="operator-auth-1",
    )
    assert not blocked.ready_for_digital_twin_dispatch
    assert set(blocked.blockers) == {
        "telemetry_not_configured", "fail_safe_not_tested",
        "operator_confirmed_capacity_missing",
    }
