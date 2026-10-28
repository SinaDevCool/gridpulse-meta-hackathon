"""Exhaustive modeled N-1 policy and publication-aware outage overlays."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from grid_data.network_study import NetworkModelInput


def exhaustive_n_minus_one(model: NetworkModelInput) -> NetworkModelInput:
    contingencies: list[dict[str, Any]] = []
    for branch in model.branches:
        contingencies.append(
            {
                "id": f"n-1-line-{branch['id']}",
                "element_type": "line",
                "element_id": str(branch["id"]),
            }
        )
    for transformer in model.transformers:
        contingencies.append(
            {
                "id": f"n-1-transformer-{transformer['id']}",
                "element_type": "transformer",
                "element_id": str(transformer["id"]),
            }
        )
    return replace(model, contingencies=contingencies)


def apply_known_outages(model: NetworkModelInput, outage_ids: tuple[str, ...]) -> NetworkModelInput:
    """Remove already-outaged assets before generating the remaining N-1 set."""

    outages = set(outage_ids)
    branches = [item for item in model.branches if str(item["id"]) not in outages]
    transformers = [item for item in model.transformers if str(item["id"]) not in outages]
    return exhaustive_n_minus_one(replace(model, branches=branches, transformers=transformers))
