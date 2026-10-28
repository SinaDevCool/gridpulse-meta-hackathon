"""Canonical reconstruction entry point delegating sampling to the ensemble authority."""

from __future__ import annotations

from capacity_backtest.contracts import TruthClass
from grid_data.network_study import NetworkModelInput

from .contracts import CandidatePCC, NetworkModelRealization
from .ensemble import build_network_ensemble


def reconstruct_network_ensemble(
    base_model: NetworkModelInput,
    pccs: tuple[CandidatePCC, ...],
    *,
    samples_per_pcc: int,
    seed: int,
    load_scale_bounds: tuple[float, float] = (0.85, 1.15),
    branch_rating_scale_bounds: tuple[float, float] = (0.8, 1.1),
    transformer_rating_scale_bounds: tuple[float, float] = (0.8, 1.1),
) -> tuple[NetworkModelRealization, ...]:
    """Construct experimental realizations without creating a second sampling implementation."""
    return build_network_ensemble(
        base_model,
        pccs,
        samples_per_pcc=samples_per_pcc,
        seed=seed,
        load_scale_bounds=load_scale_bounds,
        branch_rating_scale_bounds=branch_rating_scale_bounds,
        transformer_rating_scale_bounds=transformer_rating_scale_bounds,
        truth_class=TruthClass.EXPERIMENTAL_ESTIMATE,
    )
