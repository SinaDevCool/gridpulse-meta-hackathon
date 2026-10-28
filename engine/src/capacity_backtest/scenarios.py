"""Annual demand and flexibility scenarios with explicit physical limits."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import TruthClass


@dataclass(frozen=True)
class Battery:
    power_mw: float
    energy_mwh: float
    efficiency: float = 0.9
    initial_soc_mwh: float = 0.0
    minimum_soc_mwh: float = 0.0
    charge_efficiency: float = 0.9


def apply_battery(load_mw: list[float], threshold_mw: float, battery: Battery) -> dict[str, object]:
    if not 0 < battery.efficiency <= 1 or min(battery.power_mw, battery.energy_mwh) < 0:
        raise ValueError("invalid battery parameters")
    soc = min(max(battery.initial_soc_mwh, 0.0), battery.energy_mwh)
    net: list[float] = []
    discharged = 0.0
    for demand in load_mw:
        required = max(0.0, demand - threshold_mw)
        output = min(required, battery.power_mw, soc * battery.efficiency)
        soc -= output / battery.efficiency
        discharged += output
        net.append(demand - output)
    return {
        "net_load_mw": net,
        "discharged_mwh": discharged,
        "remaining_soc_mwh": soc,
        "hours_above_threshold": sum(value > threshold_mw for value in net),
        "truth_class": TruthClass.SYNTHETIC_DEMONSTRATION.value,
        "capacity_claim": False,
    }


def annual_summary(load_mw: list[float], threshold_mw: float) -> dict[str, object]:
    if len(load_mw) != 8760:
        raise ValueError("annual scenario requires exactly 8,760 hourly values")
    return {
        "hours": len(load_mw),
        "peak_mw": max(load_mw),
        "mean_mw": sum(load_mw) / len(load_mw),
        "hours_above_threshold": sum(value > threshold_mw for value in load_mw),
        "truth_class": TruthClass.SYNTHETIC_DEMONSTRATION.value,
        "capacity_claim": False,
    }


def apply_rechargeable_battery(
    load_mw: list[float], threshold_mw: float, battery: Battery
) -> dict[str, object]:
    """Peak-shave and recharge below the threshold without simultaneous operation."""
    if not 0 < battery.efficiency <= 1 or not 0 < battery.charge_efficiency <= 1:
        raise ValueError("invalid battery efficiency")
    if min(battery.power_mw, battery.energy_mwh, battery.minimum_soc_mwh) < 0:
        raise ValueError("invalid battery parameters")
    if battery.minimum_soc_mwh > battery.energy_mwh:
        raise ValueError("minimum state of charge exceeds energy capacity")
    soc = min(max(battery.initial_soc_mwh, battery.minimum_soc_mwh), battery.energy_mwh)
    net, soc_trace = [], []
    discharged = charged = 0.0
    for demand in load_mw:
        if demand > threshold_mw:
            available = max(0.0, soc - battery.minimum_soc_mwh) * battery.efficiency
            output = min(demand - threshold_mw, battery.power_mw, available)
            soc -= output / battery.efficiency
            discharged += output
            value = demand - output
        else:
            room = max(0.0, battery.energy_mwh - soc) / battery.charge_efficiency
            input_mw = min(threshold_mw - demand, battery.power_mw, room)
            soc += input_mw * battery.charge_efficiency
            charged += input_mw
            value = demand + input_mw
        net.append(value)
        soc_trace.append(soc)
    return {
        "net_load_mw": net, "soc_mwh": soc_trace, "charged_mwh": charged,
        "discharged_mwh": discharged,
        "equivalent_cycles": discharged / battery.energy_mwh if battery.energy_mwh else 0.0,
        "remaining_soc_mwh": soc,
        "hours_above_threshold": sum(value > threshold_mw for value in net),
        "truth_class": TruthClass.SYNTHETIC_DEMONSTRATION.value, "capacity_claim": False,
    }
