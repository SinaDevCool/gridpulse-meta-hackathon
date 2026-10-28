"""Stateful battery capability with uncertainty, derating, reserve, and degradation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from functools import cached_property

from capacity_backtest.domain.base import parse_aware_timestamp


@dataclass(frozen=True)
class BatteryConfig:
    resource_id: str
    rated_power_mw: float
    rated_energy_mwh: float
    initial_soc_mwh: float
    minimum_reserve_mwh: float
    terminal_target_mwh: float
    charge_efficiency: float = 0.92
    discharge_efficiency: float = 0.92
    self_discharge_fraction_per_hour: float = 0.0
    degradation_fraction: float = 0.0
    soc_uncertainty_mwh: float = 0.0
    unavailable_hours: tuple[int, ...] = ()
    cold_derating_per_degree: float = 0.01
    hot_derating_per_degree: float = 0.01
    normal_temperature_min_c: float = 5.0
    normal_temperature_max_c: float = 35.0
    maximum_charge_power_mw: float | None = None
    maximum_soc_fraction: float = 1.0
    critical_load_mw: float = 0.0
    backup_autonomy_minutes: float = 0.0
    ramp_rate_mw_per_minute: float | None = None
    initial_power_mw: float = 0.0
    minimum_dwell_minutes: float = 0.0
    initial_mode: str = "idle"
    initial_mode_minutes: float = 0.0
    unavailable_at: tuple[str, ...] = ()

    @cached_property
    def unavailable_instants(self):
        return frozenset(parse_aware_timestamp(value, "battery unavailable timestamp")
                         for value in self.unavailable_at)

    @cached_property
    def unavailable_indexes(self):
        return frozenset(self.unavailable_hours)

    def validate(self) -> None:
        if not self.resource_id:
            raise ValueError("battery resource_id is required")
        if len(self.unavailable_instants) != len(self.unavailable_at):
            raise ValueError("battery unavailable timestamps must be unique")
        values = (
            self.rated_power_mw, self.rated_energy_mwh, self.initial_soc_mwh,
            self.minimum_reserve_mwh, self.terminal_target_mwh, self.soc_uncertainty_mwh,
        )
        if not all(isfinite(value) for value in (*values, self.charge_efficiency,
                self.discharge_efficiency, self.self_discharge_fraction_per_hour,
                self.degradation_fraction, self.maximum_soc_fraction, self.critical_load_mw,
                self.backup_autonomy_minutes, self.cold_derating_per_degree,
                self.hot_derating_per_degree, self.normal_temperature_min_c,
                self.normal_temperature_max_c)):
            raise ValueError("battery values must be finite")
        if self.maximum_charge_power_mw is not None and (
            not isfinite(self.maximum_charge_power_mw) or self.maximum_charge_power_mw < 0
        ):
            raise ValueError("maximum charge power must be finite and nonnegative")
        if not isfinite(self.initial_power_mw) or not -(
            self.maximum_charge_power_mw if self.maximum_charge_power_mw is not None else self.rated_power_mw
        ) <= self.initial_power_mw <= self.rated_power_mw:
            raise ValueError("initial battery power exceeds capability")
        if self.ramp_rate_mw_per_minute is not None and (
            not isfinite(self.ramp_rate_mw_per_minute) or self.ramp_rate_mw_per_minute <= 0
        ):
            raise ValueError("battery ramp rate must be finite and positive")
        if (self.initial_mode not in {"idle", "charge", "discharge"}
                or not isfinite(self.minimum_dwell_minutes) or self.minimum_dwell_minutes < 0
                or not isfinite(self.initial_mode_minutes) or self.initial_mode_minutes < 0):
            raise ValueError("battery operating mode or dwell state is invalid")
        if ((self.initial_power_mw > 0 and self.initial_mode != "discharge")
                or (self.initial_power_mw < 0 and self.initial_mode != "charge")):
            raise ValueError("initial battery mode conflicts with initial power")
        if not 0 < self.maximum_soc_fraction <= 1 or min(self.critical_load_mw, self.backup_autonomy_minutes) < 0:
            raise ValueError("battery SOC ceiling or backup obligation is invalid")
        if min(values) < 0 or self.rated_power_mw <= 0 or self.rated_energy_mwh <= 0:
            raise ValueError("battery power and energy values are invalid")
        if max(self.initial_soc_mwh, self.minimum_reserve_mwh, self.terminal_target_mwh) > self.rated_energy_mwh:
            raise ValueError("battery SOC values cannot exceed rated energy")
        if not 0 < self.charge_efficiency <= 1 or not 0 < self.discharge_efficiency <= 1:
            raise ValueError("battery efficiencies must be in (0, 1]")
        if not 0 <= self.self_discharge_fraction_per_hour < 1:
            raise ValueError("self-discharge must be in [0, 1)")
        if not 0 <= self.degradation_fraction < 1:
            raise ValueError("battery degradation must be in [0, 1)")
        if min(self.cold_derating_per_degree, self.hot_derating_per_degree) < 0:
            raise ValueError("temperature derating cannot be negative")
        if self.normal_temperature_min_c > self.normal_temperature_max_c:
            raise ValueError("temperature bounds are reversed")
        ceiling = self.rated_energy_mwh * (1 - self.degradation_fraction) * self.maximum_soc_fraction
        floor = max(self.minimum_reserve_mwh,
                    self.critical_load_mw * self.backup_autonomy_minutes / 60 / self.discharge_efficiency)
        if max(self.initial_soc_mwh, self.terminal_target_mwh + self.soc_uncertainty_mwh,
               floor + self.soc_uncertainty_mwh) > ceiling + 1e-9:
            raise ValueError("battery initial state, reserve or terminal target exceeds effective SOC ceiling")


@dataclass(frozen=True)
class BatteryRequest:
    timestamp: str
    power_mw: float
    temperature_c: float = 20.0
    operating_mode: str | None = None

    def validate(self) -> None:
        parse_aware_timestamp(self.timestamp, "battery request timestamp")
        if not isfinite(self.power_mw) or not isfinite(self.temperature_c):
            raise ValueError("battery request power and temperature must be finite")
        if self.operating_mode not in {None, "charge", "discharge"}:
            raise ValueError("invalid requested battery operating mode")
        if ((self.power_mw > 1e-9 and self.operating_mode == "charge")
                or (self.power_mw < -1e-9 and self.operating_mode == "discharge")):
            raise ValueError("battery power conflicts with requested operating mode")


@dataclass(frozen=True)
class BatteryPoint:
    timestamp: str
    requested_power_mw: float
    delivered_power_mw: float
    soc_mwh: float
    usable_energy_mwh: float
    available_power_mw: float
    shortfall_mw: float
    availability: bool


@dataclass(frozen=True)
class BatteryTrajectory:
    resource_id: str
    points: tuple[BatteryPoint, ...]
    ending_soc_mwh: float
    terminal_target_met: bool
    equivalent_full_cycles: float
    delivered_mwh: float
    shortfall_mwh: float


def battery_temperature_factor(config: BatteryConfig, temperature: float) -> float:
    """Return the canonical temperature derating factor used by planning and replay."""

    config.validate()
    if temperature < config.normal_temperature_min_c:
        loss = (config.normal_temperature_min_c - temperature) * config.cold_derating_per_degree
    elif temperature > config.normal_temperature_max_c:
        loss = (temperature - config.normal_temperature_max_c) * config.hot_derating_per_degree
    else:
        loss = 0.0
    return max(0.0, 1 - loss)


def battery_available(config: BatteryConfig, interval_index: int, timestamp: str | None = None) -> bool:
    """Timestamp availability survives horizon slicing; legacy indexes remain explicit."""
    config.validate()
    if interval_index < 0:
        raise ValueError("battery interval index cannot be negative")
    if interval_index in config.unavailable_indexes:
        return False
    if config.unavailable_at:
        if timestamp is None:
            raise ValueError("timestamp-based battery availability requires an interval timestamp")
        instant = parse_aware_timestamp(timestamp, "battery interval timestamp")
        return instant not in config.unavailable_instants
    return True


def available_battery_power_mw(
    config: BatteryConfig, *, interval_index: int, temperature_c: float, timestamp: str | None = None
) -> float:
    """Return exogenous battery power capability before SOC/energy constraints."""
    if not battery_available(config, interval_index, timestamp):
        return 0.0
    return config.rated_power_mw * battery_temperature_factor(config, temperature_c)


def simulate_battery(config: BatteryConfig, requests: list[BatteryRequest], *,
                     interval_hours: float | None = None) -> BatteryTrajectory:
    """Positive request discharges; negative request charges. SOC is conservatively observed."""

    config.validate()
    if not requests:
        raise ValueError("battery simulation requires requests")
    for request in requests:
        request.validate()
    timestamps = [parse_aware_timestamp(item.timestamp, "battery request timestamp") for item in requests]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise ValueError("battery requests must be unique and chronological")
    if interval_hours is not None and (not isfinite(interval_hours) or interval_hours <= 0):
        raise ValueError("battery interval duration must be finite and positive")
    explicit_duration = interval_hours
    effective_energy = config.rated_energy_mwh * (1 - config.degradation_fraction) * config.maximum_soc_fraction
    reserve = max(config.minimum_reserve_mwh,
                  config.critical_load_mw * config.backup_autonomy_minutes / 60 / config.discharge_efficiency)
    soc = min(config.initial_soc_mwh, effective_energy)
    points = []
    discharged = charged = shortfall = 0.0
    prior_power = config.initial_power_mw
    prior_mode, mode_minutes = config.initial_mode, config.initial_mode_minutes
    for index, request in enumerate(requests):
        if explicit_duration is not None:
            interval_hours = explicit_duration
            if index and abs((timestamps[index] - timestamps[index - 1]).total_seconds() / 3600 - interval_hours) > 1e-9:
                raise ValueError("battery timestamps do not match explicit interval duration")
        elif len(timestamps) == 1:
            interval_hours = 1.0
        elif index:
            interval_hours = (timestamps[index] - timestamps[index - 1]).total_seconds() / 3600
        else:
            interval_hours = (timestamps[1] - timestamps[0]).total_seconds() / 3600
        if interval_hours <= 0:
            raise ValueError("battery request interval must be positive")
        mode = request.operating_mode or (
            "discharge" if request.power_mw > 1e-9 else "charge" if request.power_mw < -1e-9 else prior_mode
        )
        if mode != prior_mode:
            if prior_mode != "idle" and mode_minutes + 1e-8 < config.minimum_dwell_minutes:
                raise ValueError("battery replay violates minimum mode dwell")
            mode_minutes = 0.0
        prior_mode = mode
        mode_minutes += interval_hours * 60
        soc *= max(0.0, 1 - config.self_discharge_fraction_per_hour * interval_hours)
        conservative_soc = max(0.0, soc - config.soc_uncertainty_mwh)
        available = battery_available(config, index, request.timestamp)
        power_limit = available_battery_power_mw(
            config, interval_index=index, temperature_c=request.temperature_c, timestamp=request.timestamp
        )
        if request.power_mw >= 0:
            usable = max(0.0, conservative_soc - reserve)
            delivered = min(
                request.power_mw,
                power_limit,
                usable * config.discharge_efficiency / interval_hours,
            )
            soc -= delivered * interval_hours / config.discharge_efficiency
            discharged += delivered * interval_hours
            deficit = request.power_mw - delivered
        else:
            room = max(0.0, effective_energy - soc) / (
                config.charge_efficiency * interval_hours
            )
            charge_limit = (config.maximum_charge_power_mw if config.maximum_charge_power_mw is not None
                            else config.rated_power_mw) * battery_temperature_factor(config, request.temperature_c)
            charge = min(-request.power_mw, charge_limit if available else 0.0, room)
            soc += charge * config.charge_efficiency * interval_hours
            charged += charge * interval_hours
            delivered = -charge
            deficit = max(0.0, -request.power_mw - charge)
        if config.ramp_rate_mw_per_minute is not None and abs(delivered - prior_power) > (
            config.ramp_rate_mw_per_minute * interval_hours * 60 + 1e-8
        ):
            raise ValueError("battery replay violates ramp limit")
        prior_power = delivered
        shortfall += deficit * interval_hours
        points.append(
            BatteryPoint(
                request.timestamp, request.power_mw, delivered, soc,
                max(0.0, conservative_soc - reserve), power_limit,
                deficit, available,
            )
        )
    throughput = discharged + charged
    return BatteryTrajectory(
        resource_id=config.resource_id,
        points=tuple(points),
        ending_soc_mwh=soc,
        terminal_target_met=max(0.0, soc - config.soc_uncertainty_mwh) + 1e-9
        >= config.terminal_target_mwh,
        equivalent_full_cycles=throughput / (2 * effective_energy),
        delivered_mwh=discharged,
        shortfall_mwh=shortfall,
    )
