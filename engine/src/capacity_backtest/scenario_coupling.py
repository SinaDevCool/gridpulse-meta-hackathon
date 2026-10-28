"""Conservative coupling from public risk evidence to mock operating scenarios."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioSelection:
    scenario_id: str
    reserve_soc_adder: float
    evidence_resolution: str
    physical_mw_adjustment: float | None
    warnings: tuple[str, ...]


def select_mock_scenario(
    risk_probability: float | None,
    *,
    known_outage: bool,
    source_available: bool,
    evidence_resolution: str,
) -> ScenarioSelection:
    """Select stress class only; regional probability never creates a nodal MW derating."""
    if risk_probability is not None and not 0 <= risk_probability <= 1:
        raise ValueError("risk probability must be between zero and one")
    if known_outage:
        scenario, reserve = "published_outage_stress", 0.20
    elif not source_available:
        scenario, reserve = "missing_source_stress", 0.20
    elif risk_probability is not None and risk_probability >= 0.7:
        scenario, reserve = "high_regional_risk", 0.15
    elif risk_probability is not None and risk_probability >= 0.4:
        scenario, reserve = "moderate_regional_risk", 0.10
    else:
        scenario, reserve = "reference", 0.05
    return ScenarioSelection(
        scenario,
        reserve,
        evidence_resolution,
        None,
        (
            "Scenario selection is synthetic and does not allocate regional evidence to a node.",
            "A physical MW envelope must come from the selected AC network scenario.",
        ),
    )
