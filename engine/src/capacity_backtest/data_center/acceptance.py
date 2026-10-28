"""One physical acceptance rule, separate from job completion and optimality."""
from typing import Any


def accepted_optimization(result: Any, *, allow_feasible_incumbent: bool = True) -> bool:
    statuses = {"optimal"}
    if allow_feasible_incumbent:
        statuses.add("feasible_not_proven_optimal")
    return bool(
        result.status in statuses
        and result.assessment is not None
        and result.assessment.feasible
        and not result.diagnostics
        and result.facility is not None
        and result.portfolio is not None
        and not result.automatic_live_dispatch_authorized
    )
