"""Bounded open-loop common-command MILP built from canonical scenario models.

All commands are nonanticipative across the whole horizon. This is not adaptive
recourse, a calibrated probability guarantee, or a second physical model.
"""
from dataclasses import replace

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, OptimizeResult, milp
from scipy.sparse import block_diag, coo_matrix, vstack

from .acceptance import accepted_optimization
from .optimizer import optimize_facility_flexibility
from .solver_support import feasible_incumbent
from .uncertainty import UncertaintyScenario


class _Captured(Exception):
    pass


# Physical commands/state-machine decisions must agree; scenario electrical states
# and peak/import auxiliaries remain scenario-dependent.
_SHARED = {"workload", "workload_start", "charge", "discharge", "charge_mode",
           "battery_mode_change", "cooling_reduction", "cooling_recovery", "job_state", "job_progress"}


def optimize_common_plan(inputs: dict, scenarios: tuple[UncertaintyScenario, ...]) -> dict:
    if not 1 <= len(scenarios) <= 4 or len({s.scenario_id for s in scenarios}) != len(scenarios):
        raise ValueError("common-plan analysis requires 1 to 4 unique scenarios")
    policy = inputs["policy"]
    if len(inputs["intervals"]) > 96 or not 0 < policy.solver_time_limit_seconds <= 30:
        raise ValueError("common-plan horizon or solve-time budget exceeded")
    for scenario in scenarios:
        scenario.validate(len(inputs["intervals"]))
    if abs(sum(s.probability for s in scenarios) - 1) > 1e-9:
        raise ValueError("assumed scenario weights must sum to one")
    models, scenario_inputs = [], []
    for scenario in scenarios:
        values = {**inputs, "policy": replace(policy, battery_temperature_c=scenario.battery_temperature_c),
                  "onsite_generation_mw": scenario.onsite_generation_mw}
        def capture(names, objective, **kwargs):
            models.append((names, objective, kwargs))
            raise _Captured()
        try:
            optimize_facility_flexibility(**values, _model_solver=capture)
        except _Captured:
            pass
        scenario_inputs.append(values)
        if sum(len(m[0]) for m in models) > policy.maximum_variables:
            raise ValueError("combined MILP variable budget exceeded")
    names = models[0][0]
    if any(m[0] != names for m in models):
        raise ValueError("scenario decision structures must match")
    width = len(names)
    base = block_diag([m[2]["constraints"].A for m in models], format="csc")
    rows, columns, data = [], [], []
    shared = [i for i, name in enumerate(names) if name[0] in _SHARED]
    for scenario_index in range(1, len(models)):
        for column in shared:
            row = len(rows) // 2
            rows.extend((row, row)); columns.extend((column, scenario_index * width + column)); data.extend((1., -1.))
    links = coo_matrix((data, (rows, columns)), shape=(len(rows) // 2, width * len(models))).tocsc()
    matrix = vstack((base, links), format="csc")
    lb = np.concatenate([m[2]["constraints"].lb for m in models] + [np.zeros(links.shape[0])])
    ub = np.concatenate([m[2]["constraints"].ub for m in models] + [np.zeros(links.shape[0])])
    objective = np.concatenate([m[1] * s.probability for m, s in zip(models, scenarios)])
    solved = milp(objective, integrality=np.concatenate([m[2]["integrality"] for m in models]),
                  bounds=Bounds(np.concatenate([m[2]["bounds"].lb for m in models]),
                                np.concatenate([m[2]["bounds"].ub for m in models])),
                  constraints=LinearConstraint(matrix, lb, ub),
                  options={"presolve": True, "time_limit": policy.solver_time_limit_seconds})
    replays = []
    valid = feasible_incumbent(solved, matrix, np.concatenate([m[2]["bounds"].lb for m in models]),
                               np.concatenate([m[2]["bounds"].ub for m in models]), lb, ub,
                               np.concatenate([m[2]["integrality"] for m in models]))
    if valid:
        for index, values in enumerate(scenario_inputs):
            def use_solution(actual_names, actual_objective, scenario_index=index, **kwargs):
                if actual_names != names:
                    raise ValueError("canonical model changed during replay")
                x = solved.x[scenario_index * width:(scenario_index + 1) * width]
                # Joint optimality cannot be attributed to each scenario separately.
                return OptimizeResult(x=x, fun=float(actual_objective @ x), status=1)
            replays.append(optimize_facility_flexibility(**values, _model_solver=use_solution))
    accepted = len(replays) == len(scenarios) and all(accepted_optimization(r) for r in replays)
    return {"evaluation_method": "common_command_scenario_milp", "common_plan_validated": accepted,
            "accepted": accepted, "solver_status": int(solved.status),
            "joint_optimality_gap": float(solved.mip_gap) if getattr(solved, "mip_gap", None) is not None and np.isfinite(solved.mip_gap) else None,
            "scenario_weights_basis": "assumed_not_calibrated_probability",
            "outcomes": [{"scenario_id": s.scenario_id, "weight": s.probability, "result": r} for s, r in zip(scenarios, replays)],
            "limitations": ["Open-loop commands shared across all supplied scenarios; no adaptive recourse.",
                            "Acceptance covers only the supplied scenarios and canonical physical replay.",
                            "No calibrated failure probability, capacity claim or physical dispatch."],
            "capacity_claim": False, "automatic_live_dispatch_authorized": False}
