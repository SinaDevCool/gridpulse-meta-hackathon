"""Capacity-readiness diagnostics kept separate from source normalization."""

from __future__ import annotations

from dataclasses import dataclass

from grid_data.network_study import NetworkModelInput, NetworkStudyProvider


@dataclass(frozen=True)
class CapacityReadiness:
    structurally_valid: bool
    base_case_converged: bool
    base_case_passed: bool
    capacity_ready: bool
    blockers: tuple[str, ...]
    diagnostics: dict[str, object]


def assess_capacity_readiness(
    model: NetworkModelInput, provider: NetworkStudyProvider
) -> CapacityReadiness:
    blockers = []
    required = ("source_url", "license")
    structurally_valid = bool(model.buses and model.branches and model.connection_bus) and all(
        model.provenance.get(key) for key in required
    )
    if not structurally_valid:
        blockers.append("structural_or_provenance_failure")
    result = provider.run_base_case(model)
    converged = result.converged is True
    passed = converged and result.values.get("passes") is True
    if not converged:
        blockers.append("base_case_non_convergence")
    elif not passed:
        blockers.extend(
            str(item) for item in result.values.get("violations", ["base_case_violation"])
        )
    for field in (
        "operating_injections",
        "voltage_control_schedule",
        "confirmed_pcc",
        "operator_contingency_policy",
    ):
        if not model.provenance.get(field):
            blockers.append(f"missing_{field}")
    return CapacityReadiness(
        structurally_valid,
        converged,
        passed,
        structurally_valid and passed and not blockers,
        tuple(dict.fromkeys(blockers)),
        result.values,
    )
