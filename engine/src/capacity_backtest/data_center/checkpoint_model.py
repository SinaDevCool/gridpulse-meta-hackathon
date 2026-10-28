"""Executable checkpoint state constraints inside the sole facility MILP."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from math import ceil
from typing import Any

from capacity_backtest.domain.base import parse_aware_timestamp

from .contracts import AIWorkload, PlanningInterval


def checkpoint_state_count(job: AIWorkload, dt: float) -> int:
    return 5 + max(1, ceil(job.checkpoint_duration_minutes / (dt * 60))) + max(1, ceil(job.restart_duration_minutes / (dt * 60)))


@dataclass(frozen=True)
class CheckpointModel:
    states: dict[tuple[int, str], int]
    overhead_columns: dict[int, tuple[int, ...]]


def add_checkpoint_constraints(
    job: AIWorkload, intervals: tuple[PlanningInterval, ...], options: tuple[Any, ...],
    x: dict, add: Callable, constrain: Callable, dt: float,
) -> CheckpointModel:
    """One-hot execution states; overhead is quantised exactly like canonical replay."""
    cp = [f"checkpoint-{i}" for i in range(max(1, ceil(job.checkpoint_duration_minutes / (dt * 60))))]
    restart = [f"restart-{i}" for i in range(max(1, ceil(job.restart_duration_minutes / (dt * 60))))]
    names = ["pending", "running", "paused", "completed", *cp, *restart]
    predecessors = {
        "pending": ["pending"], "running": ["pending", "running", restart[-1]],
        "paused": ["paused", cp[-1]], "completed": ["completed", "running"],
        cp[0]: ["running"], restart[0]: ["paused", cp[-1]],
    }
    predecessors.update({state: [cp[i - 1]] for i, state in enumerate(cp) if i})
    predecessors.update({state: [restart[i - 1]] for i, state in enumerate(restart) if i})
    initial = {"running", cp[0]} if job.initially_running else {"pending", "running"}
    if job.initial_execution_state == "paused":
        initial = {"paused", restart[0]}
    elif job.initial_execution_state in {"checkpointing", "restarting"}:
        sequence = cp if job.initial_execution_state == "checkpointing" else restart
        remaining_stages = ceil(job.initial_overhead_remaining_minutes / (dt * 60))
        initial = {sequence[len(sequence) - remaining_stages]}
    states = {
        (interval.index, state): add(("job_state", job.workload_id, interval.index, state),
                                    0, int(interval.index > 0 or state in initial), 0, 1)
        for interval in intervals for state in names
    }
    remaining = (job.remaining_work_minutes if job.remaining_work_minutes is not None else job.expected_duration_minutes) / 60
    progress = {interval.index: add(("job_progress", job.workload_id, interval.index),
                                   0, remaining + dt, 0) for interval in intervals}
    latest = (parse_aware_timestamp(job.earliest_start, "earliest start") +
              timedelta(minutes=job.maximum_start_delay_minutes)) if job.maximum_start_delay_minutes is not None else None
    for interval in intervals:
        i = interval.index
        constrain({states[i, state]: 1 for state in names}, 1, 1)
        run = {x[job.workload_id, i, option_index]: 1 for option_index in range(len(options))}
        run[states[i, "running"]] = -1
        constrain(run, 0, 0)
        work = {progress[i]: 1}
        work.update({x[job.workload_id, i, option_index]: -option.throughput * dt
                     for option_index, option in enumerate(options)})
        if i:
            work[progress[i - 1]] = -1
            for state in names:
                transition = {states[i, state]: 1}
                transition.update({states[i - 1, prior]: -1 for prior in predecessors[state]})
                constrain(transition, -float("inf"), 0)
            # Once all work is completed, only the completed state may follow.
            constrain({progress[i - 1]: 1, states[i, "completed"]: -(remaining + dt)},
                      -float("inf"), remaining - 1e-5)
            constrain({progress[i - 1]: 1, states[i, "completed"]: -remaining}, 0, float("inf"))
            if latest is not None and parse_aware_timestamp(interval.start, "start") > latest:
                constrain({states[i, "running"]: 1, states[i - 1, "pending"]: 1}, 0, 1)
        elif latest is not None and not job.initially_running and parse_aware_timestamp(interval.start, "start") > latest:
            constrain({states[i, "running"]: 1}, 0, 0)
        constrain(work, 0, 0)
    constrain({progress[len(intervals) - 1]: 1}, remaining, float("inf"))
    constrain({states[interval.index, cp[0]]: 1 for interval in intervals
               if not (interval.index == 0 and job.initial_execution_state == "checkpointing")},
              0, job.sla.maximum_pauses - job.initial_pause_count)
    return CheckpointModel(states, {interval.index: tuple(states[interval.index, state] for state in [*cp, *restart])
                                    for interval in intervals})
