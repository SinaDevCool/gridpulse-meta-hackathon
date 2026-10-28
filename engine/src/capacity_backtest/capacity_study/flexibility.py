"""Thin reuse boundary over the existing Phase 2 dependable-capacity implementation."""

from capacity_backtest.phase1.capacity import Phase1CapacityAssessment
from capacity_backtest.phase2.battery import BatteryTrajectory
from capacity_backtest.phase2.capacity import (
    DependableCapacityAssessment,
    build_dependable_capacity_assessment,
)
from capacity_backtest.phase2.credibility import PortfolioCredibility
from capacity_backtest.phase2.fatigue import FatigueAssessment
from capacity_backtest.phase2.phase_power import PhasePowerAssessment
from capacity_backtest.phase2.thermal_workload import ThermalWorkloadTrajectory


def assess_dependable_flexibility(
    phase1: Phase1CapacityAssessment,
    credibility: PortfolioCredibility,
    fatigue: FatigueAssessment,
    phase_power: PhasePowerAssessment,
    batteries: list[BatteryTrajectory],
    thermal_workload: ThermalWorkloadTrajectory,
) -> DependableCapacityAssessment:
    return build_dependable_capacity_assessment(
        phase1, credibility, fatigue, phase_power, batteries, thermal_workload
    )
