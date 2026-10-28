"""Sparse MILP assembly and termination semantics; no alternative planning engine."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.sparse import csc_matrix  # type: ignore[import-untyped]


def constraint_matrix(rows: Sequence[dict[int, float]], width: int) -> csc_matrix:
    """Allocate only nonzero coefficients, rather than rows times variables."""
    row_indexes, columns, values = [], [], []
    for index, coefficients in enumerate(rows):
        for column, value in coefficients.items():
            if value:
                row_indexes.append(index)
                columns.append(column)
                values.append(value)
    return csc_matrix((values, (row_indexes, columns)), shape=(len(rows), width))


def termination_status(status: int) -> str:
    return {
        0: "optimal",
        1: "limit_reached",
        2: "infeasible",
        3: "unbounded",
    }.get(status, "solver_error")


def feasible_incumbent(solved, matrix, lower, upper, row_lower, row_upper, integrality) -> bool:
    """A timeout incumbent must satisfy the actual model before physical replay."""
    if solved.status not in (0, 1) or solved.x is None or solved.fun is None:
        return False
    values = np.asarray(solved.x, dtype=float)
    if values.shape != (len(lower),) or not np.all(np.isfinite(values)):
        return False
    if not np.isfinite(solved.fun):
        return False
    tolerance = 1e-7
    if np.any(values < np.asarray(lower) - tolerance) or np.any(values > np.asarray(upper) + tolerance):
        return False
    integers = values[np.asarray(integrality) != 0]
    if np.any(np.abs(integers - np.round(integers)) > tolerance):
        return False
    activity = matrix @ values
    return bool(
        np.all(activity >= np.asarray(row_lower) - tolerance)
        and np.all(activity <= np.asarray(row_upper) + tolerance)
    )


def finite_metric(value) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None
