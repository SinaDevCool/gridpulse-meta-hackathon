"""End-to-end hidden-parameter reconstruction validation on SimBench networks."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from capacity_backtest.contracts import TruthClass
from capacity_backtest.storage import atomic_write
from grid_data.network_study import NetworkModelInput, PandapowerProvider

from .contracts import CandidatePCC, PCCStatus
from .ensemble import build_network_ensemble
from .network_adapter import simbench_network
from .validation import ReconstructionCase, evaluate_reconstruction


def validate_simbench_reconstruction(
    data_root: Path,
    *,
    codes: tuple[str, ...],
    samples: int = 12,
    seed: int = 2025,
) -> Path:
    provider = PandapowerProvider(maximum_capacity_mw=50.0)
    cases = []
    details = []
    for case_index, code in enumerate(codes):
        truth_model = simbench_network(code)
        truth = provider.calculate_import_capacity(truth_model).values
        pcc = CandidatePCC(
            f"{code}-pcc", truth_model.connection_bus, "simbench", 0.4, None, None, None,
            PCCStatus.RECONSTRUCTED, 0.5, TruthClass.SYNTHETIC_DEMONSTRATION,
        )
        ensemble = build_network_ensemble(
            truth_model, (pcc,), samples_per_pcc=samples, seed=seed + case_index,
            load_scale_bounds=(0.8, 1.2), branch_rating_scale_bounds=(0.75, 1.25),
            transformer_rating_scale_bounds=(0.75, 1.25),
            truth_class=TruthClass.SYNTHETIC_DEMONSTRATION,
        )
        results = []
        rejected = 0
        for item in ensemble:
            if not isinstance(item.model, NetworkModelInput):
                continue
            try:
                results.append(provider.calculate_import_capacity(item.model).values)
            except ValueError:
                rejected += 1
        if not results:
            raise ValueError(f"all reconstructed realizations were infeasible for {code}")
        capacities = np.asarray([float(item["firm_import_capacity_mw"]) for item in results])
        bindings = [str(item["binding_constraint"]) for item in results]
        predicted_binding = Counter(bindings).most_common(1)[0][0]
        case = ReconstructionCase(
            code,
            float(truth["firm_import_capacity_mw"]),
            float(np.quantile(capacities, 0.05)),
            float(np.quantile(capacities, 0.5)),
            float(np.quantile(capacities, 0.95)),
            str(truth["binding_constraint"]),
            predicted_binding,
        )
        cases.append(case)
        details.append(
            {**case.__dict__, "sample_count": samples, "infeasible_realization_count": rejected}
        )
    metrics = evaluate_reconstruction(cases)
    payload = {
        **metrics,
        "schema_version": "gridpulse-simbench-hidden-validation-v1",
        "cases": details,
        "truth_class": "synthetic_demonstration",
        "capacity_claim": False,
    }
    destination = data_root / "quality" / "validation" / "simbench-hidden-v1.json"
    atomic_write(destination, (json.dumps(payload, indent=2) + "\n").encode())
    return destination
