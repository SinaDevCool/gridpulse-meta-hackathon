"""Derate Phase 1 conditional capacity into a dependable resource-backed envelope."""

from __future__ import annotations

from dataclasses import dataclass, replace

from capacity_backtest.phase1.capacity import Phase1CapacityAssessment

from .battery import BatteryTrajectory
from .credibility import PortfolioCredibility
from .fatigue import FatigueAssessment
from .phase_power import PhasePowerAssessment
from .thermal_workload import ThermalWorkloadTrajectory

PHASE2_CAPACITY_SCHEMA_VERSION = "gridpulse-dependable-capacity-assessment-v1"


@dataclass(frozen=True)
class DependableCapacityAssessment:
    phase1: Phase1CapacityAssessment
    dependable_conditional_envelope_mw: tuple[float, ...]
    dependable_conditional_capacity_mw: float
    dependable_activatable_capacity_mw: float
    non_delivery_reserve_mw: float
    portfolio_credibility: PortfolioCredibility
    fatigue: FatigueAssessment
    phase_power: PhasePowerAssessment
    battery_terminal_targets_met: bool
    recovery_complete: bool
    release_gate_passed: bool
    blockers: tuple[str, ...]
    schema_version: str = PHASE2_CAPACITY_SCHEMA_VERSION

    def validate(self) -> None:
        self.phase1.validate()
        if len(self.dependable_conditional_envelope_mw) != len(
            self.phase1.chronological_conditional_envelope_mw
        ):
            raise ValueError("dependable envelope must align with Phase 1")
        if any(
            dependable < firm - 1e-9 or dependable > conditional + 1e-9
            for dependable, firm, conditional in zip(
                self.dependable_conditional_envelope_mw,
                self.phase1.chronological_firm_envelope_mw,
                self.phase1.chronological_conditional_envelope_mw,
            )
        ):
            raise ValueError("dependable envelope must remain between firm and conditional")
        if self.release_gate_passed != (not self.blockers):
            raise ValueError("release gate and blockers are inconsistent")


def build_dependable_capacity_assessment(
    phase1: Phase1CapacityAssessment,
    credibility: PortfolioCredibility,
    fatigue: FatigueAssessment,
    phase_power: PhasePowerAssessment,
    batteries: list[BatteryTrajectory],
    thermal_workload: ThermalWorkloadTrajectory,
) -> DependableCapacityAssessment:
    phase1.validate()
    declared = credibility.declared_power_mw
    credibility_fraction = credibility.dependable_power_mw / declared if declared else 0.0
    firm_series = phase1.chronological_firm_envelope_mw
    dependable = tuple(
        firm + (conditional - firm) * credibility_fraction
        for firm, conditional in zip(firm_series, phase1.chronological_conditional_envelope_mw)
    )
    blockers = []
    if phase1.risk_metrics.get("release_gate_passed") is not True:
        blockers.append("phase1_risk_gate")
    if not fatigue.passed:
        blockers.append("fatigue_limits")
    if not phase_power.passed:
        blockers.append("phase_or_reactive_limits")
    battery_targets = all(item.terminal_target_met for item in batteries)
    if not battery_targets:
        blockers.append("battery_terminal_soc")
    recovery_complete = (
        thermal_workload.ending_thermal_debt_mwh <= 1e-9
        and thermal_workload.ending_workload_backlog_mwh <= 1e-9
        and thermal_workload.deadline_violation_hours == 0
    )
    if not recovery_complete:
        blockers.append("incomplete_recovery")
    if credibility.dependable_power_mw <= 0 and any(
        conditional > firm + 1e-9
        for firm, conditional in zip(firm_series, phase1.chronological_conditional_envelope_mw)
    ):
        blockers.append("no_dependable_resource_delivery")
    # Keep the legacy scalar conservative. Availability-qualified conditional
    # capacities are calculated separately from the complete chronology.
    conditional_capacity = min(dependable)
    phase1_result = replace(
        phase1.result,
        conditional_capacity_mw=conditional_capacity,
        activatable_capacity_mw=min(
            phase1.result.activatable_capacity_mw or conditional_capacity, conditional_capacity
        ),
        unknown_constraints=(
            *phase1.result.unknown_constraints,
            "Phase 2 remains modelled until operator acceptance.",
        ),
    )
    governed_phase1 = replace(phase1, result=phase1_result)
    result = DependableCapacityAssessment(
        governed_phase1,
        dependable,
        conditional_capacity,
        phase1_result.activatable_capacity_mw or 0.0,
        credibility.non_delivery_reserve_mw,
        credibility,
        fatigue,
        phase_power,
        battery_targets,
        recovery_complete,
        not blockers,
        tuple(blockers),
    )
    result.validate()
    return result
