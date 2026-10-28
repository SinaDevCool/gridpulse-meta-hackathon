"""Deterministic workload action state machine."""

from __future__ import annotations

from datetime import timedelta

from capacity_backtest.domain.base import parse_aware_timestamp

from .contracts import (
    AIWorkload,
    PlanningInterval,
    ScheduledWorkloadAction,
    WorkloadActionKind,
    WorkloadKind,
    WorkloadStatus,
    WorkloadTrajectory,
    WorkloadTrajectoryPoint,
    validate_intervals,
)
from .power_profiles import PiecewiseLinearPowerProfile


def simulate_workload(
    workload: AIWorkload,
    profile: PiecewiseLinearPowerProfile,
    intervals: tuple[PlanningInterval, ...],
    actions: tuple[ScheduledWorkloadAction, ...],
    *,
    initial_site_id: str,
) -> WorkloadTrajectory:
    workload.validate()
    profile.validate()
    validate_intervals(intervals)
    if profile.workload_id != workload.workload_id or initial_site_id not in workload.allowed_site_ids:
        raise ValueError("workload, profile, and initial site do not align")
    by_interval: dict[int, ScheduledWorkloadAction] = {}
    for scheduled_action in actions:
        scheduled_action.validate()
        if (
            scheduled_action.workload_id != workload.workload_id
            or scheduled_action.interval_index >= len(intervals)
        ):
            raise ValueError("scheduled action does not align with workload horizon")
        if scheduled_action.interval_index in by_interval:
            raise ValueError("only one workload action is allowed per interval")
        by_interval[scheduled_action.interval_index] = scheduled_action
    if workload.workload_kind == WorkloadKind.CRITICAL_INFERENCE and any(
        action.action_kind != WorkloadActionKind.NO_ACTION for action in actions
    ):
        raise ValueError("critical workloads cannot be curtailed or moved")
    remaining = (workload.remaining_work_minutes if workload.remaining_work_minutes is not None
                 else workload.expected_duration_minutes) / 60
    earliest = parse_aware_timestamp(workload.earliest_start, "earliest start")
    deadline = parse_aware_timestamp(workload.sla.deadline, "deadline")
    status = WorkloadStatus.RUNNING if workload.initially_running else WorkloadStatus.PENDING
    if workload.initial_execution_state is not None:
        status = WorkloadStatus(workload.initial_execution_state)
    started = workload.initially_running or workload.initial_execution_state is not None
    site = initial_site_id
    pauses, movements = workload.initial_pause_count, workload.initial_movement_count
    overhead_minutes = workload.initial_overhead_remaining_minutes
    overhead_kind: WorkloadStatus | None = status if overhead_minutes else None
    points = []
    completion_time = None
    for interval in intervals:
        start = parse_aware_timestamp(interval.start, "interval start")
        action = by_interval.get(interval.index)
        gpu_count = workload.nominal_gpu_count
        power_cap = workload.nominal_power_mw
        power = throughput = completed = 0.0
        overhead = False
        if remaining <= 1e-12:
            status = WorkloadStatus.COMPLETED
        elif overhead_minutes > 0:
            status = overhead_kind or status
            overhead = True
            power = workload.minimum_power_cap_mw
            overhead_minutes = max(0, overhead_minutes - interval.duration_minutes)
            if overhead_minutes == 0:
                status = (
                    WorkloadStatus.PAUSED
                    if overhead_kind == WorkloadStatus.CHECKPOINTING
                    else WorkloadStatus.RUNNING
                )
        elif action and action.action_kind == WorkloadActionKind.CHECKPOINT_AND_PAUSE:
            if status not in {WorkloadStatus.RUNNING, WorkloadStatus.PENDING}:
                raise ValueError("only a runnable workload can checkpoint")
            pauses += 1
            if pauses > workload.sla.maximum_pauses:
                raise ValueError("workload maximum pause count exceeded")
            status, overhead = WorkloadStatus.CHECKPOINTING, True
            power = workload.minimum_power_cap_mw
            overhead_minutes = max(0, workload.checkpoint_duration_minutes - interval.duration_minutes)
            overhead_kind = WorkloadStatus.CHECKPOINTING
            if overhead_minutes == 0:
                status = WorkloadStatus.PAUSED
        elif action and action.action_kind == WorkloadActionKind.RESUME:
            if status != WorkloadStatus.PAUSED:
                raise ValueError("resume requires a paused workload")
            status, overhead = WorkloadStatus.RESTARTING, True
            power = workload.minimum_power_cap_mw
            overhead_minutes = max(0, workload.restart_duration_minutes - interval.duration_minutes)
            overhead_kind = WorkloadStatus.RESTARTING
            if overhead_minutes == 0:
                status = WorkloadStatus.RUNNING
        elif status == WorkloadStatus.PAUSED:
            pass
        elif (
            action and action.action_kind == WorkloadActionKind.DELAY_START
        ) or start < earliest:
            if action and action.action_kind == WorkloadActionKind.DELAY_START and started:
                raise ValueError("a running workload cannot use delay_start as a free pause")
            status = WorkloadStatus.PENDING
        else:
            if not started and workload.maximum_start_delay_minutes is not None and (
                start > earliest + timedelta(minutes=workload.maximum_start_delay_minutes)
            ):
                raise ValueError("workload maximum start delay exceeded")
            started = True
            if action and action.action_kind == WorkloadActionKind.MOVE_TO_SITE:
                destination = str(action.destination_site_id)
                if not workload.geographic_movement_permitted or destination not in workload.allowed_site_ids:
                    raise ValueError("workload movement violates site restrictions")
                site, movements = destination, movements + 1
                status = WorkloadStatus.MOVED
            if action and action.action_kind == WorkloadActionKind.REDUCE_GPU_ALLOCATION:
                gpu_count = int(action.target_gpu_count or 0)
                if not workload.minimum_gpu_count <= gpu_count <= workload.maximum_gpu_count:
                    raise ValueError("GPU action exceeds workload bounds")
            if action and action.action_kind == WorkloadActionKind.POWER_CAP:
                power_cap = float(action.target_power_cap_mw or 0)
                if not workload.minimum_power_cap_mw <= power_cap <= workload.nominal_power_mw:
                    raise ValueError("power cap exceeds workload bounds")
            performance = profile.evaluate(gpu_count, power_cap)
            if performance.throughput_fraction < workload.sla.minimum_throughput_fraction:
                raise ValueError("workload action violates minimum throughput")
            status = WorkloadStatus.RUNNING if status != WorkloadStatus.MOVED else status
            power, throughput = performance.power_mw, performance.throughput_fraction
            completed = min(remaining, throughput * interval.duration_minutes / 60)
            remaining -= completed
            if remaining <= 1e-12:
                status = WorkloadStatus.COMPLETED
                completion_time = (start + timedelta(minutes=interval.duration_minutes)).isoformat()
        points.append(WorkloadTrajectoryPoint(interval.index, status, site, gpu_count, power, throughput, completed, max(0.0, remaining), overhead, overhead_minutes, pauses, movements))
    deadline_met = completion_time is not None and parse_aware_timestamp(completion_time, "completion") <= deadline
    result = WorkloadTrajectory(workload.workload_id, tuple(points), completion_time, deadline_met, pauses, movements, max(0.0, remaining))
    result.validate()
    return result
