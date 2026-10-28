"""Deterministic facility flexibility optimization with mandatory physical replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import ceil, isfinite

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp  # type: ignore[import-untyped]

from capacity_backtest import __version__
from capacity_backtest.domain.base import parse_aware_timestamp
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.phase2.battery import (
    BatteryConfig,
    BatteryRequest,
    BatteryTrajectory,
    available_battery_power_mw,
    battery_available,
    battery_temperature_factor,
    simulate_battery,
)
from capacity_backtest.phase2.fatigue import FatigueAssessment, FatigueLimits, evaluate_fatigue
from capacity_backtest.phase2.thermal_workload import (
    CoolingConfig,
    WorkloadConfig,
    simulate_cooling_workload,
)

from .assessment import FacilityFlexibilityAssessment, assess_facility_flexibility
from .checkpoint_model import add_checkpoint_constraints, checkpoint_state_count
from .contracts import (
    FacilityOptimizationPolicy,
    FlexibilityEconomics,
    PlanningInterval,
    ScheduledWorkloadAction,
    WorkloadActionKind,
    WorkloadKind,
    validate_intervals,
)
from .facility import FacilityConfig, FacilityPowerTrajectory, build_facility_trajectory
from .portfolio import PortfolioTrajectory, WorkloadPortfolio, evaluate_portfolio
from .power_profiles import PiecewiseLinearPowerProfile
from .solver_support import constraint_matrix, feasible_incumbent, finite_metric, termination_status


@dataclass(frozen=True)
class OptimizationDiagnostic:
    code: str
    interval_index: int | None
    magnitude_mw: float


@dataclass(frozen=True)
class FacilityOptimizationResult:
    status: str
    solver: str
    objective_eur: float | None
    actions: tuple[ScheduledWorkloadAction, ...]
    battery_requests: tuple[BatteryRequest, ...]
    cooling_adjustment_mw: tuple[float, ...]
    portfolio: PortfolioTrajectory | None
    facility: FacilityPowerTrajectory | None
    assessment: FacilityFlexibilityAssessment | None
    fatigue: FatigueAssessment | None
    diagnostics: tuple[OptimizationDiagnostic, ...]
    model_fingerprint: str
    deterministic: bool
    automatic_live_dispatch_authorized: bool = False
    schema_version: str = "gridpulse-facility-optimization-result-v1"
    solver_termination: str = "unknown"
    optimality_gap: float | None = None
    objective_bound_eur: float | None = None
    solver_objective_eur: float | None = None
    battery_trajectories: tuple[BatteryTrajectory, ...] = ()
    intervals: tuple[PlanningInterval, ...] = ()
    baseline_facility: FacilityPowerTrajectory | None = None


@dataclass(frozen=True)
class _Option:
    workload_id: str
    gpu_count: int
    power_mw: float
    throughput: float


def _profile_options(
    portfolio: WorkloadPortfolio,
    profiles: dict[str, PiecewiseLinearPowerProfile],
    allow_caps: bool,
) -> dict[str, tuple[_Option, ...]]:
    options: dict[str, tuple[_Option, ...]] = {}
    for workload in sorted(portfolio.workloads, key=lambda item: item.workload_id):
        profile = profiles[workload.workload_id]
        profile.validate()
        rows = sorted(
            (
                point
                for point in profile.points
                if point.gpu_count == workload.nominal_gpu_count
                and point.power_cap_mw
                >= point.gpu_count * portfolio.idle_gpu_power_watts / 1_000_000
                and workload.minimum_power_cap_mw <= point.power_cap_mw <= workload.nominal_power_mw
                and point.throughput_fraction + 1e-12
                >= max(
                    workload.sla.minimum_throughput_fraction,
                    1 - workload.sla.maximum_slowdown_fraction,
                )
            ),
            key=lambda point: (point.power_cap_mw, point.throughput_fraction),
        )
        if not rows:
            raise ValueError(f"workload {workload.workload_id} has no admissible profile option")
        if workload.workload_kind == WorkloadKind.CRITICAL_INFERENCE or not allow_caps:
            rows = [
                min(
                    rows,
                    key=lambda point: (
                        abs(point.power_cap_mw - workload.nominal_power_mw),
                        -point.power_cap_mw,
                    ),
                )
            ]
        if not rows:
            raise ValueError(f"workload {workload.workload_id} has no admissible profile option")
        options[workload.workload_id] = tuple(
            _Option(workload.workload_id, row.gpu_count, row.power_cap_mw, row.throughput_fraction)
            for row in rows
        )
    return options


def _fingerprint_inputs(**values: object) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def optimize_facility_flexibility(
    requirement: FlexibilityRequirement,
    intervals: tuple[PlanningInterval, ...],
    facility: FacilityConfig,
    portfolio: WorkloadPortfolio,
    profiles: dict[str, PiecewiseLinearPowerProfile],
    policy: FacilityOptimizationPolicy,
    economics: FlexibilityEconomics,
    *,
    cooling: CoolingConfig,
    batteries: tuple[BatteryConfig, ...] = (),
    onsite_generation_mw: tuple[float, ...] | None = None,
    fatigue_limits: FatigueLimits | None = None,
    _model_solver: Callable | None = None,
) -> FacilityOptimizationResult:
    """Propose a schedule, then accept it only when canonical replay passes."""

    requirement.validate()
    validate_intervals(intervals)
    facility.validate()
    portfolio.validate()
    policy.validate()
    if not any(policy.event_intervals) and requirement.required_reduction_mw > 0:
        raise ValueError(
            "an event-free recovery horizon cannot carry an active reduction requirement"
        )
    if (
        policy.operating_target_mw is not None
        and policy.operating_target_mw > facility.import_limit_mw
    ):
        raise ValueError("operating target cannot exceed the facility import limit")
    economics.validate()
    cooling.validate()
    if requirement.site_id != facility.site_id:
        raise ValueError("requirement and facility sites do not match")
    size = len(intervals)
    import_limits = facility.import_limits(size)
    targets = policy.operating_target_profile_mw or ((policy.operating_target_mw,) * size)
    if any(target is not None and target > limit for target, limit in zip(targets, import_limits)):
        raise ValueError("operating target cannot exceed its interval connection limit")
    if len(policy.event_intervals) != size or len(economics.import_price_eur_per_mwh) != size:
        raise ValueError("optimizer inputs must align with the planning horizon")
    if len(portfolio.workloads) > policy.maximum_workloads:
        raise ValueError("workload portfolio exceeds the configured optimizer scale limit")
    if set(profiles) != {job.workload_id for job in portfolio.workloads}:
        raise ValueError("portfolio profiles must match workload identities exactly")
    if len({battery.resource_id for battery in batteries}) != len(batteries):
        raise ValueError("battery resource identities must be unique")
    onsite = onsite_generation_mw or (0.0,) * size
    if len(onsite) != size:
        raise ValueError("onsite generation must align with the planning horizon")
    if any(not isfinite(value) or value < 0 for value in onsite):
        raise ValueError("onsite generation must be finite and nonnegative")
    for battery in batteries:
        battery.validate()
    options = _profile_options(portfolio, profiles, policy.allow_workload_power_caps)
    if any(
        job.execution_mode == "checkpointable"
        and job.minimum_power_cap_mw
        < job.nominal_gpu_count * portfolio.idle_gpu_power_watts / 1_000_000
        for job in portfolio.workloads
    ):
        raise ValueError("checkpoint overhead power cannot be lower than occupied GPU idle draw")
    if len({interval.duration_minutes for interval in intervals}) != 1:
        raise ValueError("optimizer requires uniform planning interval durations")
    dt = intervals[0].duration_minutes / 60
    estimated_variables = (
        size
        * (
            sum(len(rows) for rows in options.values())
            + 2 * len(portfolio.workloads)
            + 5 * len(batteries)
            + 5
            + sum(
                checkpoint_state_count(job, dt)
                for job in portfolio.workloads
                if job.execution_mode == "checkpointable"
            )
        )
        + 1
    )
    if estimated_variables > policy.maximum_variables:
        raise ValueError("MILP variable budget exceeded before model allocation")

    # Stable variable ordering is part of the deterministic contract.
    names: list[tuple[object, ...]] = []
    integrality: list[int] = []
    lower: list[float] = []
    upper: list[float] = []
    objective: list[float] = []
    economic_objective: list[float] = []

    def add(name: tuple[object, ...], lo: float, hi: float, cost: float, integer: int = 0) -> int:
        names.append(name)
        lower.append(lo)
        upper.append(hi)
        objective.append(cost + policy.deterministic_tie_break_eur * len(names))
        economic_objective.append(cost)
        integrality.append(integer)
        return len(names) - 1

    x: dict[tuple[str, int, int], int] = {}
    for workload in sorted(portfolio.workloads, key=lambda item: item.workload_id):
        earliest = parse_aware_timestamp(workload.earliest_start, "earliest start")
        deadline = parse_aware_timestamp(workload.sla.deadline, "deadline")
        for interval in intervals:
            start = parse_aware_timestamp(interval.start, "interval start")
            active = (
                start >= earliest
                and start + timedelta(minutes=interval.duration_minutes) <= deadline
            )
            for option_index, option in enumerate(options[workload.workload_id]):
                hi = 1.0 if active else 0.0
                x[workload.workload_id, interval.index, option_index] = add(
                    ("workload", workload.workload_id, interval.index, option_index),
                    0.0,
                    hi,
                    0.0,
                    1,
                )
    charge: dict[tuple[int, int], int] = {}
    discharge: dict[tuple[int, int], int] = {}
    soc: dict[tuple[int, int], int] = {}
    charge_mode: dict[tuple[int, int], int] = {}
    for battery_index, battery in enumerate(batteries):
        effective_energy = (
            battery.rated_energy_mwh
            * (1 - battery.degradation_fraction)
            * battery.maximum_soc_fraction
        )
        reserve = max(
            battery.minimum_reserve_mwh,
            battery.critical_load_mw
            * battery.backup_autonomy_minutes
            / 60
            / battery.discharge_efficiency,
        )
        for interval in intervals:
            capability = (
                available_battery_power_mw(
                    battery,
                    interval_index=interval.index,
                    temperature_c=policy.battery_temperature_c[interval.index],
                    timestamp=interval.start,
                )
                if policy.allow_battery
                else 0.0
            )
            cycle_cost = economics.battery_degradation_eur_per_mwh * dt
            charge_capability = (
                (
                    battery.maximum_charge_power_mw
                    if battery.maximum_charge_power_mw is not None
                    else battery.rated_power_mw
                )
                * battery_temperature_factor(battery, policy.battery_temperature_c[interval.index])
                if policy.allow_battery
                and battery_available(battery, interval.index, interval.start)
                else 0.0
            )
            charge[battery_index, interval.index] = add(
                ("charge", battery.resource_id, interval.index), 0, charge_capability, cycle_cost
            )
            discharge[battery_index, interval.index] = add(
                ("discharge", battery.resource_id, interval.index), 0, capability, cycle_cost
            )
            soc[battery_index, interval.index] = add(
                ("soc", battery.resource_id, interval.index),
                reserve + battery.soc_uncertainty_mwh,
                effective_energy,
                0,
            )
            charge_mode[battery_index, interval.index] = add(
                ("charge_mode", battery.resource_id, interval.index), 0, 1, 0, 1
            )
    # Conservative executable subset: one uninterrupted run per job. Delaying
    # an already-running job is not a free pause/checkpoint operation.
    starts = {
        (workload.workload_id, interval.index): add(
            ("workload_start", workload.workload_id, interval.index),
            0,
            0
            if not workload.initially_running
            and workload.maximum_start_delay_minutes is not None
            and parse_aware_timestamp(interval.start, "interval")
            > parse_aware_timestamp(workload.earliest_start, "earliest start")
            + timedelta(minutes=workload.maximum_start_delay_minutes)
            else 1,
            0,
            1,
        )
        for workload in portfolio.workloads
        if workload.execution_mode == "uninterrupted"
        for interval in intervals
    }
    mode_changes = {
        (battery_index, interval.index): add(
            ("battery_mode_change", battery.resource_id, interval.index), 0, 1, 0, 1
        )
        for battery_index, battery in enumerate(batteries)
        if battery.minimum_dwell_minutes > 0
        for interval in intervals
    }
    cooling_reduction: dict[int, int] = {}
    cooling_recovery: dict[int, int] = {}
    thermal_debt: dict[int, int] = {}
    for interval in intervals:
        reduction_hi = cooling.maximum_reduction_mw if policy.allow_cooling_reduction else 0.0
        cooling_reduction[interval.index] = add(
            ("cooling_reduction", interval.index), 0, reduction_hi, 0
        )
        cooling_recovery[interval.index] = add(
            ("cooling_recovery", interval.index),
            0,
            cooling.recovery_power_mw if policy.allow_cooling_reduction else 0,
            economics.cooling_recovery_eur_per_mwh * dt,
        )
        thermal_debt[interval.index] = add(
            ("thermal_debt", interval.index), 0, cooling.maximum_thermal_debt_mwh, 0
        )
    peak = add(("peak_import",), 0, facility.import_limit_mw, economics.peak_import_eur_per_mw)
    imports = {
        interval.index: add(
            ("grid_import", interval.index),
            0,
            import_limits[interval.index],
            economics.import_price_eur_per_mwh[interval.index] * dt,
        )
        for interval in intervals
    }
    importing = {
        interval.index: add(("meter_importing", interval.index), 0, 1, 0, 1)
        for interval in intervals
    }

    rows: list[dict[int, float]] = []
    row_lb: list[float] = []
    row_ub: list[float] = []

    def constrain(coefficients: dict[int, float], lo: float, hi: float) -> None:
        rows.append(coefficients)
        row_lb.append(lo)
        row_ub.append(hi)

    checkpoint_models = {}
    for workload in sorted(portfolio.workloads, key=lambda item: item.workload_id):
        active_indexes = []
        for interval in intervals:
            columns = [
                x[workload.workload_id, interval.index, option_index]
                for option_index in range(len(options[workload.workload_id]))
            ]
            if any(upper[column] > 0 for column in columns):
                minimum_selection = (
                    1 if workload.workload_kind == WorkloadKind.CRITICAL_INFERENCE else 0
                )
                constrain({column: 1 for column in columns}, minimum_selection, 1)
                active_indexes.extend(columns)
        work = {
            x[workload.workload_id, interval.index, option_index]: option.throughput * dt
            for interval in intervals
            for option_index, option in enumerate(options[workload.workload_id])
        }
        remaining = (
            workload.remaining_work_minutes
            if workload.remaining_work_minutes is not None
            else workload.expected_duration_minutes
        )
        constrain(work, remaining / 60, np.inf)
        if workload.execution_mode == "checkpointable":
            checkpoint_models[workload.workload_id] = add_checkpoint_constraints(
                workload, intervals, options[workload.workload_id], x, add, constrain, dt
            )
            continue
        # Negative tariffs must not create fictitious post-completion job load.
        # Sparse cumulative progress gates execution once remaining work is done.
        remaining_hours = remaining / 60
        maximum_progress = (
            remaining_hours
            + max(option.throughput for option in options[workload.workload_id]) * dt
        )
        progress = {
            interval.index: add(
                ("job_progress", workload.workload_id, interval.index), 0, maximum_progress, 0
            )
            for interval in intervals
        }
        # Keep the completion separation above HiGHS' integer feasibility
        # tolerance; independent incumbent validation remains stricter.
        completion_separation_hours = 1e-4
        big_m = maximum_progress + completion_separation_hours
        for interval in intervals:
            balance = {progress[interval.index]: 1}
            if interval.index:
                balance[progress[interval.index - 1]] = -1
            balance.update(
                {
                    x[workload.workload_id, interval.index, option_index]: -option.throughput * dt
                    for option_index, option in enumerate(options[workload.workload_id])
                }
            )
            constrain(balance, 0, 0)
            execution = {
                x[workload.workload_id, interval.index, option_index]: big_m
                for option_index in range(len(options[workload.workload_id]))
            }
            if interval.index:
                execution[progress[interval.index - 1]] = 1
            constrain(execution, -np.inf, remaining_hours - completion_separation_hours + big_m)
        if workload.initially_running:
            constrain(
                {
                    x[workload.workload_id, 0, option_index]: 1
                    for option_index in range(len(options[workload.workload_id]))
                },
                1,
                1,
            )
        constrain({starts[workload.workload_id, interval.index]: 1 for interval in intervals}, 0, 1)
        for interval in intervals:
            transition = {
                x[workload.workload_id, interval.index, option_index]: 1
                for option_index in range(len(options[workload.workload_id]))
            }
            if interval.index:
                transition.update(
                    {
                        x[workload.workload_id, interval.index - 1, option_index]: -1
                        for option_index in range(len(options[workload.workload_id]))
                    }
                )
            transition[starts[workload.workload_id, interval.index]] = -1
            constrain(transition, -np.inf, 0)

    if portfolio.fleet_gpu_capacity is not None:
        for interval in intervals:
            allocation = {
                x[workload.workload_id, interval.index, option_index]: option.gpu_count
                for workload in portfolio.workloads
                for option_index, option in enumerate(options[workload.workload_id])
            }
            for workload in portfolio.workloads:
                if workload.workload_id in checkpoint_models:
                    allocation.update(
                        {
                            column: workload.nominal_gpu_count
                            for column in checkpoint_models[workload.workload_id].overhead_columns[
                                interval.index
                            ]
                        }
                    )
            constrain(allocation, 0, portfolio.fleet_gpu_capacity)

    for battery_index, battery in enumerate(batteries):
        for interval in intervals:
            mode = charge_mode[battery_index, interval.index]
            charge_column = charge[battery_index, interval.index]
            discharge_column = discharge[battery_index, interval.index]
            constrain({charge_column: 1, mode: -upper[charge_column]}, -np.inf, 0)
            constrain(
                {discharge_column: 1, mode: upper[discharge_column]},
                -np.inf,
                upper[discharge_column],
            )
            if battery.minimum_dwell_minutes > 0:
                change = mode_changes[battery_index, interval.index]
                if interval.index:
                    previous = charge_mode[battery_index, interval.index - 1]
                    constrain({mode: 1, previous: -1, change: -1}, -np.inf, 0)
                    constrain({mode: -1, previous: 1, change: -1}, -np.inf, 0)
                elif battery.initial_mode == "idle":
                    constrain({change: 1}, 1, 1)
                else:
                    initial = int(battery.initial_mode == "charge")
                    constrain({mode: 1, change: -1}, -np.inf, initial)
                    constrain({mode: -1, change: -1}, -np.inf, -initial)
                if (
                    battery.initial_mode != "idle"
                    and interval.index * dt * 60
                    < battery.minimum_dwell_minutes - battery.initial_mode_minutes
                ):
                    constrain(
                        {mode: 1},
                        int(battery.initial_mode == "charge"),
                        int(battery.initial_mode == "charge"),
                    )
                dwell_size = ceil(battery.minimum_dwell_minutes / (dt * 60))
                constrain(
                    {
                        mode_changes[battery_index, index]: 1
                        for index in range(
                            max(0, interval.index - dwell_size + 1), interval.index + 1
                        )
                    },
                    0,
                    1,
                )
            if battery.ramp_rate_mw_per_minute is not None:
                ramp = battery.ramp_rate_mw_per_minute * dt * 60
                delta = {discharge_column: 1, charge_column: -1}
                if interval.index:
                    delta[discharge[battery_index, interval.index - 1]] = -1
                    delta[charge[battery_index, interval.index - 1]] = 1
                    constrain(delta, -ramp, ramp)
                else:
                    constrain(
                        delta, battery.initial_power_mw - ramp, battery.initial_power_mw + ramp
                    )
            coefficients = {
                soc[battery_index, interval.index]: 1,
                charge[battery_index, interval.index]: -battery.charge_efficiency * dt,
                discharge[battery_index, interval.index]: dt / battery.discharge_efficiency,
            }
            if interval.index:
                coefficients[soc[battery_index, interval.index - 1]] = -(
                    1 - battery.self_discharge_fraction_per_hour * dt
                )
                constrain(coefficients, 0, 0)
            else:
                constrain(
                    coefficients,
                    battery.initial_soc_mwh * (1 - battery.self_discharge_fraction_per_hour * dt),
                    battery.initial_soc_mwh * (1 - battery.self_discharge_fraction_per_hour * dt),
                )
        constrain(
            {soc[battery_index, size - 1]: 1},
            battery.terminal_target_mwh + battery.soc_uncertainty_mwh,
            np.inf,
        )
    for interval in intervals:
        coefficients = {
            thermal_debt[interval.index]: 1,
            cooling_reduction[interval.index]: -dt,
            cooling_recovery[interval.index]: cooling.recovery_efficiency * dt,
        }
        if interval.index:
            coefficients[thermal_debt[interval.index - 1]] = -1
            constrain(coefficients, 0, 0)
        else:
            constrain(
                coefficients, cooling.initial_thermal_debt_mwh, cooling.initial_thermal_debt_mwh
            )
    constrain({thermal_debt[size - 1]: 1}, 0, 1e-9)

    baseline_portfolio = evaluate_portfolio(
        portfolio, profiles, intervals, (), site_id=facility.site_id
    )
    baseline_facility = build_facility_trajectory(
        facility, intervals, baseline_portfolio, onsite_generation_mw=onsite
    )
    loss_it = (
        1
        + facility.cooling_load_factor
        + facility.ups_loss_fraction
        + facility.distribution_loss_fraction * (1 + facility.cooling_load_factor)
    )
    loss_cooling = 1 + facility.distribution_loss_fraction
    idle_base = (portfolio.fleet_gpu_capacity or 0) * portfolio.idle_gpu_power_watts / 1_000_000
    fixed = (
        facility.cooling_baseline_mw
        + facility.networking_power_mw
        + facility.storage_power_mw
        + facility.fixed_auxiliary_power_mw
    ) * loss_cooling + idle_base * loss_it
    grid_rows: list[dict[int, float]] = []
    grid_constants: list[float] = []
    event_constraint_rows: list[int] = []
    for interval in intervals:
        grid_coefficients: dict[int, float] = {peak: -1}
        for workload in portfolio.workloads:
            for option_index, option in enumerate(options[workload.workload_id]):
                grid_coefficients[x[workload.workload_id, interval.index, option_index]] = (
                    option.power_mw - option.gpu_count * portfolio.idle_gpu_power_watts / 1_000_000
                ) * loss_it
            if workload.workload_id in checkpoint_models:
                grid_coefficients.update(
                    {
                        column: (
                            workload.minimum_power_cap_mw
                            - workload.nominal_gpu_count
                            * portfolio.idle_gpu_power_watts
                            / 1_000_000
                        )
                        * loss_it
                        for column in checkpoint_models[workload.workload_id].overhead_columns[
                            interval.index
                        ]
                    }
                )
        for battery_index, _ in enumerate(batteries):
            grid_coefficients[charge[battery_index, interval.index]] = 1
            grid_coefficients[discharge[battery_index, interval.index]] = -1
        grid_coefficients[cooling_reduction[interval.index]] = -loss_cooling
        grid_coefficients[cooling_recovery[interval.index]] = loss_cooling
        constant = fixed - onsite[interval.index]
        grid_rows.append(grid_coefficients)
        grid_constants.append(constant)
        constrain(grid_coefficients, -np.inf, -constant)
        import_coefficients = dict(grid_coefficients)
        import_coefficients.pop(peak)
        constrain(import_coefficients, -np.inf, import_limits[interval.index] - constant)
        workload_coefficients = {
            x[workload.workload_id, interval.index, option_index]: option.power_mw
            - option.gpu_count * portfolio.idle_gpu_power_watts / 1_000_000
            for workload in portfolio.workloads
            for option_index, option in enumerate(options[workload.workload_id])
        }
        for workload in portfolio.workloads:
            if workload.workload_id in checkpoint_models:
                workload_coefficients.update(
                    {
                        column: workload.minimum_power_cap_mw
                        - workload.nominal_gpu_count * portfolio.idle_gpu_power_watts / 1_000_000
                        for column in checkpoint_models[workload.workload_id].overhead_columns[
                            interval.index
                        ]
                    }
                )
        constrain(
            workload_coefficients,
            baseline_portfolio.power_points[interval.index].scheduled_it_power_mw
            * (1 - policy.maximum_workload_reduction_fraction)
            - idle_base,
            np.inf,
        )
        if targets[interval.index] is not None:
            constrain(import_coefficients, -np.inf, targets[interval.index] - constant)
        # Charge purchased energy at the meter boundary, not only GPU power.
        # Exact max(0, net demand), including negative prices. An epigraph alone
        # would let negative prices buy fictitious imports up to the facility limit.
        purchased = dict(import_coefficients)
        purchased[imports[interval.index]] = -1
        constrain(purchased, -np.inf, -constant)
        surplus_bound = max(
            0.0,
            onsite[interval.index]
            + sum(battery.rated_power_mw for battery in batteries)
            + cooling.maximum_reduction_mw * loss_cooling
            - fixed,
        )
        exact_meter = dict(purchased)
        exact_meter[importing[interval.index]] = -surplus_bound
        constrain(exact_meter, -constant - surplus_bound, np.inf)
        constrain(
            {imports[interval.index]: 1, importing[interval.index]: -import_limits[interval.index]},
            -np.inf,
            0,
        )
        if policy.event_intervals[interval.index]:
            target = (
                baseline_facility.points[interval.index].grid_import_mw
                - requirement.required_reduction_mw
            )
            event_constraint_rows.append(len(rows))
            constrain(import_coefficients, -np.inf, target - constant)
        elif requirement.rebound_limit_mw is not None:
            constrain(
                import_coefficients,
                -np.inf,
                baseline_facility.points[interval.index].grid_import_mw
                + requirement.rebound_limit_mw
                - constant,
            )

    matrix = constraint_matrix(rows, len(names))
    # The joint-scenario assembler reuses this exact model and the replay below.
    solve = (
        milp
        if _model_solver is None
        else lambda *args, **kwargs: _model_solver(tuple(names), *args, **kwargs)
    )
    solved = solve(
        np.asarray(objective),
        integrality=np.asarray(integrality),
        bounds=Bounds(np.asarray(lower), np.asarray(upper)),
        constraints=LinearConstraint(matrix, np.asarray(row_lb), np.asarray(row_ub)),
        options={"presolve": True, "time_limit": policy.solver_time_limit_seconds},
    )
    fingerprint = _fingerprint_inputs(
        engine_version=__version__,
        scipy_version=scipy.__version__,
        numpy_version=np.__version__,
        requirement=asdict(requirement),
        intervals=[asdict(item) for item in intervals],
        facility=asdict(facility),
        portfolio=asdict(portfolio),
        policy=asdict(policy),
        economics=asdict(economics),
        cooling=asdict(cooling),
        batteries=[asdict(item) for item in batteries],
        profiles={key: asdict(value) for key, value in sorted(profiles.items())},
        onsite_generation_mw=onsite,
        fatigue_limits=asdict(fatigue_limits) if fatigue_limits is not None else None,
    )
    termination = termination_status(solved.status)
    solver_metadata = {
        "solver_termination": termination,
        "optimality_gap": finite_metric(getattr(solved, "mip_gap", None)),
        "objective_bound_eur": finite_metric(getattr(solved, "mip_dual_bound", None)),
        "solver_objective_eur": finite_metric(solved.fun),
    }
    if not feasible_incumbent(solved, matrix, lower, upper, row_lb, row_ub, integrality):
        diagnostics = (
            _diagnose_shortfall(
                objective,
                integrality,
                lower,
                upper,
                rows,
                row_lb,
                row_ub,
                grid_rows,
                grid_constants,
                event_constraint_rows,
                peak,
                baseline_facility,
                requirement,
                policy,
                dt,
            )
            if termination == "infeasible"
            else (
                OptimizationDiagnostic(
                    "invalid_solver_incumbent" if termination == "optimal" else termination,
                    None,
                    0.0,
                ),
            )
        )
        return FacilityOptimizationResult(
            "solver_error" if termination == "optimal" else termination,
            "scipy-highs-milp",
            None,
            (),
            (),
            (),
            None,
            None,
            None,
            None,
            diagnostics,
            fingerprint,
            True,
            **solver_metadata,
        )

    values = solved.x
    actions: list[ScheduledWorkloadAction] = []
    for workload in sorted(portfolio.workloads, key=lambda item: item.workload_id):
        for interval in intervals:
            selected = [
                (option_index, option)
                for option_index, option in enumerate(options[workload.workload_id])
                if values[x[workload.workload_id, interval.index, option_index]] > 0.5
            ]
            if workload.workload_id in checkpoint_models:
                states = checkpoint_models[workload.workload_id].states
                action_kind = (
                    WorkloadActionKind.CHECKPOINT_AND_PAUSE
                    if values[states[interval.index, "checkpoint-0"]] > 0.5
                    else WorkloadActionKind.RESUME
                    if values[states[interval.index, "restart-0"]] > 0.5
                    else WorkloadActionKind.DELAY_START
                    if values[states[interval.index, "pending"]] > 0.5
                    else None
                )
                if action_kind is not None:
                    actions.append(
                        ScheduledWorkloadAction(
                            f"opt-{workload.workload_id}-{interval.index}",
                            workload.workload_id,
                            interval.index,
                            action_kind,
                        )
                    )
                if not selected:
                    continue
            if not selected:
                start = parse_aware_timestamp(interval.start, "interval start")
                if (
                    workload.workload_kind != WorkloadKind.CRITICAL_INFERENCE
                    and start >= parse_aware_timestamp(workload.earliest_start, "earliest start")
                    and start < parse_aware_timestamp(workload.sla.deadline, "deadline")
                ):
                    actions.append(
                        ScheduledWorkloadAction(
                            f"opt-{workload.workload_id}-{interval.index}",
                            workload.workload_id,
                            interval.index,
                            WorkloadActionKind.DELAY_START,
                        )
                    )
                continue
            _, option = selected[0]
            if abs(option.power_mw - workload.nominal_power_mw) > 1e-9:
                actions.append(
                    ScheduledWorkloadAction(
                        f"opt-{workload.workload_id}-{interval.index}",
                        workload.workload_id,
                        interval.index,
                        WorkloadActionKind.POWER_CAP,
                        target_power_cap_mw=option.power_mw,
                    )
                )
    battery_requests: list[BatteryRequest] = []
    battery_trajectories: list[BatteryTrajectory] = []
    for battery_index, battery in enumerate(batteries):
        requests = [
            BatteryRequest(
                interval.start,
                float(
                    values[discharge[battery_index, interval.index]]
                    - values[charge[battery_index, interval.index]]
                ),
                policy.battery_temperature_c[interval.index],
                "charge"
                if values[charge_mode[battery_index, interval.index]] > 0.5
                else "discharge",
            )
            for interval in intervals
        ]
        battery_requests.extend(requests)
        battery_trajectories.append(simulate_battery(battery, requests, interval_hours=dt))
    cooling_adjustment = tuple(
        float(-values[cooling_reduction[index]] + values[cooling_recovery[index]])
        for index in range(size)
    )
    replay_portfolio = evaluate_portfolio(
        portfolio, profiles, intervals, tuple(actions), site_id=facility.site_id
    )
    replay_facility = build_facility_trajectory(
        facility,
        intervals,
        replay_portfolio,
        cooling_adjustment_mw=cooling_adjustment,
        batteries=tuple(battery_trajectories),
        onsite_generation_mw=onsite,
    )
    cooling_replay = simulate_cooling_workload(
        [max(0.0, -value) for value in cooling_adjustment],
        [max(0.0, value) for value in cooling_adjustment],
        cooling,
        WorkloadConfig(0.0, 0.0, max(1, int(size * dt)), 0.0),
        interval_hours=dt,
    )
    assessment = assess_facility_flexibility(
        requirement,
        intervals,
        baseline_facility,
        replay_facility,
        replay_portfolio,
        None,
        event_intervals=policy.event_intervals,
        batteries=tuple(battery_trajectories),
        cooling_recovery_complete=cooling_replay.ending_thermal_debt_mwh <= 1e-9,
        replayed_rebound_mw=max(
            (
                max(0.0, actual.grid_import_mw - baseline.grid_import_mw)
                for actual, baseline, event in zip(
                    replay_facility.points, baseline_facility.points, policy.event_intervals
                )
                if not event
            ),
            default=0.0,
        ),
    )
    reductions = [
        max(0.0, base.grid_import_mw - actual.grid_import_mw)
        for base, actual in zip(baseline_facility.points, replay_facility.points)
    ]
    fatigue = (
        evaluate_fatigue(
            reductions,
            sum(item.equivalent_full_cycles for item in battery_trajectories),
            fatigue_limits,
            interval_hours=dt,
        )
        if fatigue_limits is not None
        else None
    )
    replay_diagnostics: list[OptimizationDiagnostic] = []
    for interval in intervals:
        index = interval.index
        modeled_it = idle_base + sum(
            (option.power_mw - option.gpu_count * portfolio.idle_gpu_power_watts / 1_000_000)
            * values[x[workload.workload_id, index, option_index]]
            for workload in portfolio.workloads
            for option_index, option in enumerate(options[workload.workload_id])
        )
        modeled_it += sum(
            (
                workload.minimum_power_cap_mw
                - workload.nominal_gpu_count * portfolio.idle_gpu_power_watts / 1_000_000
            )
            * values[column]
            for workload in portfolio.workloads
            if workload.workload_id in checkpoint_models
            for column in checkpoint_models[workload.workload_id].overhead_columns[index]
        )
        actual_it = replay_facility.points[index].it_power_mw
        if abs(modeled_it - actual_it) > 1e-7:
            replay_diagnostics.append(
                OptimizationDiagnostic(
                    "workload_replay_power_mismatch", index, abs(modeled_it - actual_it)
                )
            )
        modeled_import = max(
            0.0,
            fixed
            + loss_it * (modeled_it - idle_base)
            + loss_cooling * cooling_adjustment[index]
            + sum(
                values[charge[battery_index, index]] - values[discharge[battery_index, index]]
                for battery_index in range(len(batteries))
            )
            - onsite[index],
        )
        if abs(modeled_import - replay_facility.points[index].grid_import_mw) > 1e-7:
            replay_diagnostics.append(
                OptimizationDiagnostic(
                    "facility_replay_power_mismatch",
                    index,
                    abs(modeled_import - replay_facility.points[index].grid_import_mw),
                )
            )
    if any(battery.shortfall_mwh > 1e-8 for battery in battery_trajectories):
        replay_diagnostics.append(OptimizationDiagnostic("battery_replay_shortfall", None, 0.0))
    for point, target in zip(replay_facility.points, targets):
        if target is not None and point.grid_import_mw > target + 1e-8:
            replay_diagnostics.append(
                OptimizationDiagnostic(
                    "operating_target_not_met", point.interval_index, point.grid_import_mw - target
                )
            )
    if not assessment.feasible:
        replay_diagnostics.extend(
            OptimizationDiagnostic(code, None, 0.0) for code in assessment.blockers
        )
    if cooling_replay.ending_thermal_debt_mwh > 1e-8:
        replay_diagnostics.append(
            OptimizationDiagnostic(
                "cooling_terminal_thermal_debt", None, cooling_replay.ending_thermal_debt_mwh
            )
        )
    if fatigue is not None and not fatigue.passed:
        replay_diagnostics.extend(
            OptimizationDiagnostic(code, None, 0.0) for code in fatigue.violations
        )
    status = (
        ("optimal" if termination == "optimal" else "feasible_not_proven_optimal")
        if not replay_diagnostics
        else "replay_failed"
    )
    return FacilityOptimizationResult(
        status,
        "scipy-highs-milp",
        float(np.dot(economic_objective, values)),
        tuple(actions),
        tuple(battery_requests),
        cooling_adjustment,
        replay_portfolio,
        replay_facility,
        assessment,
        fatigue,
        tuple(replay_diagnostics),
        fingerprint,
        True,
        battery_trajectories=tuple(battery_trajectories),
        **solver_metadata,
        intervals=intervals,
        baseline_facility=baseline_facility,
    )


def _diagnose_shortfall(
    objective: list[float],
    integrality: list[int],
    lower: list[float],
    upper: list[float],
    rows: list[dict[int, float]],
    row_lb: list[float],
    row_ub: list[float],
    grid_rows: list[dict[int, float]],
    grid_constants: list[float],
    event_constraint_rows: list[int],
    peak_index: int,
    baseline: FacilityPowerTrajectory,
    requirement: FlexibilityRequirement,
    policy: FacilityOptimizationPolicy,
    dt: float,
) -> tuple[OptimizationDiagnostic, ...]:
    """Solve the same model with event-only shortfall slacks; never marks it feasible."""

    c = list(objective)
    lo = list(lower)
    hi = list(upper)
    integer = list(integrality)
    excluded = set(event_constraint_rows)
    diagnostic_rows = [row for index, row in enumerate(rows) if index not in excluded]
    diagnostic_lb = [value for index, value in enumerate(row_lb) if index not in excluded]
    diagnostic_ub = [value for index, value in enumerate(row_ub) if index not in excluded]
    slack_columns: list[tuple[int, int]] = []
    for index, active in enumerate(policy.event_intervals):
        if not active:
            continue
        column = len(c)
        c.append(policy.diagnostic_slack_penalty_eur_per_mwh * dt)
        lo.append(0)
        hi.append(np.inf)
        integer.append(0)
        coefficients = dict(grid_rows[index])
        coefficients.pop(peak_index, None)
        coefficients[column] = -1
        target = baseline.points[index].grid_import_mw - requirement.required_reduction_mw
        diagnostic_rows.append(coefficients)
        diagnostic_lb.append(-np.inf)
        diagnostic_ub.append(target - grid_constants[index])
        slack_columns.append((index, column))
    matrix = constraint_matrix(diagnostic_rows, len(c))
    solved = milp(
        np.asarray(c),
        integrality=np.asarray(integer),
        bounds=Bounds(np.asarray(lo), np.asarray(hi)),
        constraints=LinearConstraint(matrix, np.asarray(diagnostic_lb), np.asarray(diagnostic_ub)),
        options={"presolve": True, "time_limit": policy.solver_time_limit_seconds},
    )
    if not solved.success or solved.x is None:
        code = (
            "model_constraints_infeasible"
            if solved.status == 2
            else f"diagnostic_{termination_status(solved.status)}"
        )
        return (OptimizationDiagnostic(code, None, 0.0),)
    return tuple(
        OptimizationDiagnostic("flexibility_shortfall", index, float(solved.x[column]))
        for index, column in slack_columns
        if solved.x[column] > 1e-8
    ) or (OptimizationDiagnostic("non_event_model_constraint", None, 0.0),)
