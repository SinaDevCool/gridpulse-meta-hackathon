"""Reproducible uncertainty ensembles around explicit network realizations."""

from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np
from scipy.stats import qmc  # type: ignore[import-untyped]

from capacity_backtest.contracts import TruthClass
from grid_data.network_study import NetworkModelInput

from .contracts import CandidatePCC, NetworkModelRealization


def build_network_ensemble(
    base_model: NetworkModelInput,
    pccs: tuple[CandidatePCC, ...],
    *,
    samples_per_pcc: int,
    seed: int,
    load_scale_bounds: tuple[float, float] = (0.85, 1.15),
    branch_rating_scale_bounds: tuple[float, float] = (0.8, 1.1),
    transformer_rating_scale_bounds: tuple[float, float] = (0.8, 1.1),
    truth_class: TruthClass = TruthClass.EXPERIMENTAL_ESTIMATE,
) -> tuple[NetworkModelRealization, ...]:
    if not pccs or samples_per_pcc <= 0:
        raise ValueError("ensemble requires PCCs and positive sample count")
    bounds = (load_scale_bounds, branch_rating_scale_bounds, transformer_rating_scale_bounds)
    if any(low <= 0 or high < low for low, high in bounds):
        raise ValueError("ensemble scale bounds are invalid")
    sampler = qmc.LatinHypercube(d=3, rng=np.random.default_rng(seed))
    sample = sampler.random(n=len(pccs) * samples_per_pcc)
    lower = np.asarray([item[0] for item in bounds])
    upper = np.asarray([item[1] for item in bounds])
    scaled = qmc.scale(sample, lower, upper)
    results = []
    weight = 1.0 / len(scaled)
    row_index = 0
    for pcc in pccs:
        for sample_index in range(samples_per_pcc):
            load_scale, line_scale, transformer_scale = map(float, scaled[row_index])
            row_index += 1
            model = copy.deepcopy(base_model)
            loads = [
                {
                    **item,
                    "p_mw": float(item.get("p_mw", 0)) * load_scale,
                    "q_mvar": float(item.get("q_mvar", 0)) * load_scale,
                }
                for item in model.loads
            ]
            branches = [
                {**item, "max_i_ka": float(item["max_i_ka"]) * line_scale}
                for item in model.branches
            ]
            transformers = [
                {**item, "sn_mva": float(item["sn_mva"]) * transformer_scale}
                for item in model.transformers
            ]
            model = replace(
                model,
                loads=loads,
                branches=branches,
                transformers=transformers,
                connection_bus=pcc.bus_id,
            )
            realization = NetworkModelRealization(
                realization_id=f"{pcc.pcc_id}-sample-{sample_index:04d}",
                network_model_id=model.model_id,
                pcc=pcc,
                probability_weight=weight,
                random_seed=seed + row_index,
                truth_class=truth_class,
                topology_version=model.model_version,
                parameter_set_id=f"lhs-load-{load_scale:.6f}-line-{line_scale:.6f}-trafo-{transformer_scale:.6f}",
                assumptions=(
                    f"background_load_scale={load_scale:.8f}",
                    f"branch_rating_scale={line_scale:.8f}",
                    f"transformer_rating_scale={transformer_scale:.8f}",
                ),
                model=model,
            )
            realization.validate()
            results.append(realization)
    return tuple(results)
