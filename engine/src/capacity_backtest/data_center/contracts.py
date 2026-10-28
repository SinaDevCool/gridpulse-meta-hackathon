"""Canonical time, workload, action, schedule, and trajectory contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain.base import DomainContract, parse_aware_timestamp
from capacity_backtest.domain.evidence import EvidenceReference


@dataclass(frozen=True)
class PlanningInterval(DomainContract):
    index: int
    start: str
    duration_minutes: int
    schema_version: str = "gridpulse-planning-interval-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-planning-interval-v1":
            raise ValueError("unsupported planning-interval schema")
        if self.index < 0 or self.duration_minutes not in {15, 30, 60}:
            raise ValueError("planning interval index or duration is invalid")
        parse_aware_timestamp(self.start, "planning interval start")


def validate_intervals(intervals: tuple[PlanningInterval, ...]) -> None:
    if not intervals:
        raise ValueError("planning intervals cannot be empty")
    for interval in intervals:
        interval.validate()
    if [item.index for item in intervals] != list(range(len(intervals))):
        raise ValueError("planning interval indexes must be contiguous from zero")
    starts = [parse_aware_timestamp(item.start, "planning interval start") for item in intervals]
    for prior, current, interval in zip(starts, starts[1:], intervals):
        elapsed_minutes = (current - prior).total_seconds() / 60
        if elapsed_minutes != interval.duration_minutes:
            raise ValueError("planning intervals must be contiguous without gaps or overlaps")


class WorkloadKind(str, Enum):
    CRITICAL_INFERENCE = "critical_inference"
    LATENCY_SENSITIVE_INFERENCE = "latency_sensitive_inference"
    BATCH_INFERENCE = "batch_inference"
    TRAINING = "training"
    FINE_TUNING = "fine_tuning"
    DATA_PROCESSING = "data_processing"


class WorkloadActionKind(str, Enum):
    NO_ACTION = "no_action"
    POWER_CAP = "power_cap"
    REDUCE_GPU_ALLOCATION = "reduce_gpu_allocation"
    DELAY_START = "delay_start"
    CHECKPOINT_AND_PAUSE = "checkpoint_and_pause"
    RESUME = "resume"
    MOVE_TO_SITE = "move_to_site"


class WorkloadStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CHECKPOINTING = "checkpointing"
    PAUSED = "paused"
    RESTARTING = "restarting"
    COMPLETED = "completed"
    MOVED = "moved"


@dataclass(frozen=True)
class WorkloadSLA(DomainContract):
    deadline: str
    maximum_slowdown_fraction: float
    minimum_throughput_fraction: float
    maximum_pauses: int
    latency_boundary_ms: float | None
    penalty_eur: float
    schema_version: str = "gridpulse-workload-sla-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-workload-sla-v1":
            raise ValueError("unsupported workload SLA schema")
        parse_aware_timestamp(self.deadline, "workload deadline")
        if not 0 <= self.maximum_slowdown_fraction < 1:
            raise ValueError("maximum slowdown must be in [0, 1)")
        if not 0 < self.minimum_throughput_fraction <= 1:
            raise ValueError("minimum throughput must be in (0, 1]")
        if self.maximum_pauses < 0 or self.penalty_eur < 0:
            raise ValueError("pause count and SLA penalty cannot be negative")
        if self.latency_boundary_ms is not None and self.latency_boundary_ms <= 0:
            raise ValueError("latency boundary must be positive")


@dataclass(frozen=True)
class AIWorkload(DomainContract):
    workload_id: str
    tenant_id: str
    workload_kind: WorkloadKind
    earliest_start: str
    nominal_gpu_count: int
    minimum_gpu_count: int
    maximum_gpu_count: int
    nominal_power_mw: float
    minimum_power_cap_mw: float
    expected_duration_minutes: int
    checkpoint_duration_minutes: int
    restart_duration_minutes: int
    geographic_movement_permitted: bool
    allowed_site_ids: tuple[str, ...]
    data_residency_regions: tuple[str, ...]
    sla: WorkloadSLA
    truth_class: TruthClass
    evidence_cutoff: str
    evidence: tuple[EvidenceReference, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    schema_version: str = "gridpulse-ai-workload-v1"
    maximum_start_delay_minutes: int | None = None
    initially_running: bool = False
    remaining_work_minutes: float | None = None
    execution_mode: str = "uninterrupted"
    initial_execution_state: str | None = None
    initial_overhead_remaining_minutes: int = 0
    initial_pause_count: int = 0
    initial_movement_count: int = 0

    def validate(self) -> None:
        if self.schema_version != "gridpulse-ai-workload-v1":
            raise ValueError("unsupported AI-workload schema")
        if not self.workload_id or not self.tenant_id:
            raise ValueError("workload and tenant identifiers are required")
        start = parse_aware_timestamp(self.earliest_start, "earliest start")
        cutoff = parse_aware_timestamp(self.evidence_cutoff, "workload evidence cutoff")
        self.sla.validate()
        if start >= parse_aware_timestamp(self.sla.deadline, "workload deadline"):
            raise ValueError("earliest start must precede deadline")
        if not 0 <= self.minimum_gpu_count <= self.nominal_gpu_count <= self.maximum_gpu_count:
            raise ValueError("workload GPU bounds are invalid")
        if self.nominal_power_mw <= 0 or not 0 < self.minimum_power_cap_mw <= self.nominal_power_mw:
            raise ValueError("workload power bounds are invalid")
        if (
            self.expected_duration_minutes <= 0
            or min(self.checkpoint_duration_minutes, self.restart_duration_minutes) < 0
        ):
            raise ValueError("workload durations are invalid")
        if self.maximum_start_delay_minutes is not None and self.maximum_start_delay_minutes < 0:
            raise ValueError("maximum start delay cannot be negative")
        if self.execution_mode not in {"uninterrupted", "checkpointable"}:
            raise ValueError("unsupported workload execution mode")
        if self.execution_mode == "checkpointable" and (
            self.sla.maximum_pauses < 1 or self.workload_kind == WorkloadKind.CRITICAL_INFERENCE
        ):
            raise ValueError("checkpoint scheduling requires explicit noncritical pause permission")
        if self.initial_execution_state not in {None, "paused", "checkpointing", "restarting"}:
            raise ValueError("unsupported initial execution state")
        if self.initial_execution_state is not None and (
            self.execution_mode != "checkpointable" or self.initially_running
        ):
            raise ValueError("carried checkpoint state requires checkpointable non-running input")
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v < 0
            for v in (
                self.initial_overhead_remaining_minutes,
                self.initial_pause_count,
                self.initial_movement_count,
            )
        ):
            raise ValueError("carried overhead and counters must be nonnegative integers")
        if self.initial_pause_count > self.sla.maximum_pauses or self.initial_movement_count:
            raise ValueError("carried pause count exceeds permission or migration is unsupported")
        overhead_limit = (
            self.checkpoint_duration_minutes
            if self.initial_execution_state == "checkpointing"
            else self.restart_duration_minutes
        )
        if self.initial_execution_state in {"checkpointing", "restarting"}:
            if not 0 < self.initial_overhead_remaining_minutes <= overhead_limit:
                raise ValueError("carried overhead must fit its declared duration")
        elif self.initial_overhead_remaining_minutes:
            raise ValueError("overhead requires checkpointing or restarting state")
        if (
            self.remaining_work_minutes is not None
            and not 0 < self.remaining_work_minutes <= self.expected_duration_minutes
        ):
            raise ValueError("remaining work must be positive and no larger than declared duration")
        if (
            len(self.allowed_site_ids) != len(set(self.allowed_site_ids))
            or not self.allowed_site_ids
        ):
            raise ValueError("allowed site identifiers must be non-empty and unique")
        if self.geographic_movement_permitted and len(self.allowed_site_ids) < 2:
            raise ValueError("movable workloads require at least two allowed sites")
        if not self.geographic_movement_permitted and len(self.allowed_site_ids) != 1:
            raise ValueError("non-movable workloads must have exactly one allowed site")
        if not self.data_residency_regions:
            raise ValueError("at least one data-residency region is required")
        truth = coerce_truth_class(self.truth_class)
        if self.workload_kind == WorkloadKind.CRITICAL_INFERENCE:
            critical = (
                self.minimum_gpu_count == self.nominal_gpu_count
                and self.sla.minimum_throughput_fraction == 1
                and self.sla.maximum_slowdown_fraction == 0
                and self.sla.maximum_pauses == 0
            )
            if not critical:
                raise ValueError("critical inference must be fully protected")
        for item in self.evidence:
            item.validate()
            if parse_aware_timestamp(item.retrieved_at, "retrieved_at") > cutoff:
                raise ValueError("workload evidence exceeds its cutoff")
            if truth == TruthClass.OPERATOR_CONFIRMED and item.truth_class != truth:
                raise ValueError("operator-confirmed workload requires matching evidence")


@dataclass(frozen=True)
class ScheduledWorkloadAction(DomainContract):
    action_id: str
    workload_id: str
    interval_index: int
    action_kind: WorkloadActionKind
    target_gpu_count: int | None = None
    target_power_cap_mw: float | None = None
    destination_site_id: str | None = None
    assumption_ids: tuple[str, ...] = ()
    schema_version: str = "gridpulse-workload-action-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-workload-action-v1":
            raise ValueError("unsupported workload-action schema")
        if not self.action_id or not self.workload_id or self.interval_index < 0:
            raise ValueError("workload action identity or interval is invalid")
        if self.action_kind == WorkloadActionKind.POWER_CAP and self.target_power_cap_mw is None:
            raise ValueError("power-cap action requires target power")
        if (
            self.action_kind == WorkloadActionKind.REDUCE_GPU_ALLOCATION
            and self.target_gpu_count is None
        ):
            raise ValueError("GPU-reduction action requires target GPU count")
        if self.action_kind == WorkloadActionKind.MOVE_TO_SITE and not self.destination_site_id:
            raise ValueError("move action requires destination site")


@dataclass(frozen=True)
class WorkloadTrajectoryPoint:
    interval_index: int
    status: WorkloadStatus
    site_id: str
    gpu_count: int
    power_mw: float
    throughput_fraction: float
    completed_work_hours: float
    remaining_work_hours: float
    checkpoint_or_restart: bool
    overhead_remaining_minutes: int = 0
    pause_count: int = 0
    movement_count: int = 0


@dataclass(frozen=True)
class WorkloadTrajectory(DomainContract):
    workload_id: str
    points: tuple[WorkloadTrajectoryPoint, ...]
    completion_time: str | None
    deadline_met: bool
    pause_count: int
    movement_count: int
    ending_remaining_work_hours: float
    schema_version: str = "gridpulse-workload-trajectory-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-workload-trajectory-v1" or not self.points:
            raise ValueError("invalid workload trajectory")
        if [point.interval_index for point in self.points] != list(range(len(self.points))):
            raise ValueError("workload trajectory must align with planning intervals")
        if min(self.pause_count, self.movement_count, self.ending_remaining_work_hours) < 0:
            raise ValueError("workload trajectory counters cannot be negative")


@dataclass(frozen=True)
class FlexibilityEconomics(DomainContract):
    """Optional planning costs; never a source of physical feasibility."""

    import_price_eur_per_mwh: tuple[float, ...]
    battery_degradation_eur_per_mwh: float = 0.0
    cooling_recovery_eur_per_mwh: float = 0.0
    peak_import_eur_per_mw: float = 0.0
    schema_version: str = "gridpulse-flexibility-economics-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-flexibility-economics-v1":
            raise ValueError("unsupported flexibility-economics schema")
        if not self.import_price_eur_per_mwh:
            raise ValueError("at least one import price is required")
        values = (
            *self.import_price_eur_per_mwh,
            self.battery_degradation_eur_per_mwh,
            self.cooling_recovery_eur_per_mwh,
            self.peak_import_eur_per_mw,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("economic coefficients must be finite")
        if (
            min(
                self.battery_degradation_eur_per_mwh,
                self.cooling_recovery_eur_per_mwh,
                self.peak_import_eur_per_mw,
            )
            < 0
        ):
            raise ValueError("non-energy economic coefficients cannot be negative")


@dataclass(frozen=True)
class FacilityOptimizationPolicy(DomainContract):
    """Explicit bounds for the single canonical facility optimizer."""

    event_intervals: tuple[bool, ...]
    battery_temperature_c: tuple[float, ...]
    allow_workload_power_caps: bool = True
    allow_battery: bool = True
    allow_cooling_reduction: bool = True
    diagnostic_slack_penalty_eur_per_mwh: float = 1_000_000.0
    deterministic_tie_break_eur: float = 1e-7
    solver_time_limit_seconds: float = 300.0
    maximum_workloads: int = 5000
    schema_version: str = "gridpulse-facility-optimization-policy-v1"
    maximum_variables: int = 250_000
    operating_target_mw: float | None = None
    maximum_workload_reduction_fraction: float = 1.0
    operating_target_profile_mw: tuple[float, ...] | None = None

    def validate(self) -> None:
        if self.schema_version != "gridpulse-facility-optimization-policy-v1":
            raise ValueError("unsupported facility-optimization policy schema")
        if not self.event_intervals or any(
            not isinstance(value, bool) for value in self.event_intervals
        ):
            raise ValueError("optimization policy requires a nonempty boolean event horizon")
        if len(self.battery_temperature_c) != len(self.event_intervals):
            raise ValueError("battery temperatures must align with the event horizon")
        if self.diagnostic_slack_penalty_eur_per_mwh <= 0:
            raise ValueError("diagnostic slack penalty must be positive")
        if self.deterministic_tie_break_eur <= 0:
            raise ValueError("deterministic tie break must be positive")
        if self.solver_time_limit_seconds <= 0 or self.maximum_workloads < 1:
            raise ValueError("optimizer scale and time limits must be positive")
        if (
            not isfinite(self.solver_time_limit_seconds)
            or self.solver_time_limit_seconds > 3600
            or not 1 <= self.maximum_variables <= 1_000_000
        ):
            raise ValueError("optimizer time or variable budget exceeds qualification bounds")
        if self.operating_target_mw is not None and (
            not isfinite(self.operating_target_mw) or self.operating_target_mw <= 0
        ):
            raise ValueError("operating target must be finite and positive")
        if self.operating_target_profile_mw is not None and (
            len(self.operating_target_profile_mw) != len(self.event_intervals)
            or any(
                isinstance(value, bool) or not isfinite(value) or value < 0
                for value in self.operating_target_profile_mw
            )
        ):
            raise ValueError("operating targets must be finite, nonnegative and aligned")
        if not 0 <= self.maximum_workload_reduction_fraction <= 1:
            raise ValueError("maximum workload reduction fraction must be in [0, 1]")
