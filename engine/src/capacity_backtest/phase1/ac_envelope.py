"""Unified chronological AC N-0/N-1 envelope construction and verification."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Protocol

from capacity_backtest.contracts import TruthClass
from capacity_backtest.domain import NetworkEnvelope
from capacity_backtest.domain.base import parse_aware_timestamp
from grid_data.network_study import NetworkModelInput, StudyResult


class CapacityProvider(Protocol):
    def calculate_import_capacity(self, model: NetworkModelInput) -> StudyResult: ...


@dataclass(frozen=True)
class OperatingState:
    timestamp: str
    committed_load_mw: float
    committed_generation_mw: float = 0.0
    reactive_power_mvar: float | None = None
    reserved_capacity_mw: float = 0.0

    def validate(self) -> None:
        parse_aware_timestamp(self.timestamp, "operating-state timestamp")
        if min(self.committed_load_mw, self.committed_generation_mw, self.reserved_capacity_mw) < 0:
            raise ValueError("operating-state powers cannot be negative")


@dataclass(frozen=True)
class ACStateResult:
    timestamp: str
    n0_import_mw: float
    n1_import_mw: float
    reserved_capacity_mw: float
    binding_case: str
    binding_constraint: str
    capacity_is_lower_bound: bool
    search_tolerance_mw: float
    reactive_power_mvar: float


@dataclass(frozen=True)
class ACEnvelopeStudy:
    envelope: NetworkEnvelope
    states: tuple[ACStateResult, ...]
    physics_verified: bool
    limitations: tuple[str, ...]


def run_ac_envelope_study(
    model: NetworkModelInput,
    states: list[OperatingState],
    provider: CapacityProvider,
    *,
    power_factor: float,
    truth_class: TruthClass,
    envelope_id: str,
) -> ACEnvelopeStudy:
    if not 0 < power_factor <= 1:
        raise ValueError("power_factor must be in (0, 1]")
    if not states:
        raise ValueError("AC envelope study requires operating states")
    parsed = []
    rows = []
    for state in states:
        state.validate()
        parsed.append(parse_aware_timestamp(state.timestamp, "operating-state timestamp"))
        total_committed_load_mw = state.committed_load_mw + state.reserved_capacity_mw
        q_mvar = state.reactive_power_mvar
        if q_mvar is None:
            q_mvar = total_committed_load_mw * math.tan(math.acos(power_factor))
        operating_model = replace(
            model,
            loads=[
                *model.loads,
                {
                    "id": f"phase1-committed-{state.timestamp}",
                    "bus": model.connection_bus,
                    "p_mw": total_committed_load_mw,
                    "q_mvar": q_mvar,
                },
            ],
            generators=[
                *model.generators,
                *(
                    [
                        {
                            "id": f"phase1-generation-{state.timestamp}",
                            "bus": model.connection_bus,
                            "p_mw": state.committed_generation_mw,
                            "q_mvar": 0.0,
                        }
                    ]
                    if state.committed_generation_mw
                    else []
                ),
            ],
        )
        result = provider.calculate_import_capacity(operating_model)
        if result.status == "unavailable" or result.converged is not True:
            raise ValueError(f"AC capacity calculation unavailable at {state.timestamp}")
        values = result.values
        # Reservations are already represented as physical load in ``operating_model``.
        # Subtracting them again from the provider's incremental headroom would double count them.
        n0 = max(0.0, float(values["base_case_capacity_mw"]))
        n1 = max(0.0, float(values["firm_import_capacity_mw"]))
        if n1 > n0 + 1e-9:
            raise ValueError("physics provider returned N-1 capacity above N-0")
        rows.append(
            ACStateResult(
                timestamp=state.timestamp,
                n0_import_mw=n0,
                n1_import_mw=n1,
                reserved_capacity_mw=state.reserved_capacity_mw,
                binding_case=str(values.get("binding_case", "unknown")),
                binding_constraint=str(values.get("binding_constraint", "unknown")),
                capacity_is_lower_bound=bool(values.get("capacity_is_lower_bound", False)),
                search_tolerance_mw=float(values.get("search_tolerance_mw", 0.0)),
                reactive_power_mvar=q_mvar,
            )
        )
    if parsed != sorted(parsed) or len(parsed) != len(set(parsed)):
        raise ValueError("operating states must be unique and chronological")
    envelope = NetworkEnvelope(
        envelope_id=envelope_id,
        network_model_id=model.model_id,
        candidate_bus_id=model.connection_bus,
        timestamps=tuple(row.timestamp for row in rows),
        n0_import_mw=tuple(row.n0_import_mw for row in rows),
        n1_import_mw=tuple(row.n1_import_mw for row in rows),
        binding_constraints=tuple(row.binding_constraint for row in rows),
        truth_class=truth_class,
    )
    envelope.validate()
    return ACEnvelopeStudy(
        envelope=envelope,
        states=tuple(rows),
        physics_verified=True,
        limitations=(
            "Steady-state AC thermal and voltage constraints only.",
            "Protection, harmonics, short-circuit and dynamic stability remain outside Phase 1.",
        ),
    )
