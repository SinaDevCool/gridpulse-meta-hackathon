"""Canonical interval screening for declared flexible-connection envelopes."""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise
from typing import Any

from .facility import ENGINE_VERSION, _fingerprint

FCA_INTERVAL_REQUEST_SCHEMA = "gridpulse-fca-interval-request-v1"
FCA_INTERVAL_RESULT_SCHEMA = "gridpulse-fca-interval-application-result-v1"


def _interval_minutes(points: list[dict[str, Any]]) -> int:
    if not points:
        raise ValueError("interval profile is empty")
    if len(points) == 1:
        return 15
    times = [datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00")) for item in points]
    deltas = [int((right - left).total_seconds() / 60) for left, right in pairwise(times)]
    if not deltas or deltas[0] not in {15, 30, 60} or any(value != deltas[0] for value in deltas):
        raise ValueError("profile contains missing, duplicate, or inconsistent intervals")
    return deltas[0]


def _round(value: float) -> float:
    return round(value, 3)


def _dispatch(points: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    minutes = _interval_minutes(points)
    duration = minutes / 60
    efficiency = min(1.0, max(0.01, float(settings["battery_round_trip_efficiency"])))
    battery_energy = max(0.0, float(settings["battery_energy_mwh"]))
    usable = max(0.0, battery_energy * (1 - float(settings["battery_minimum_soc"])))
    soc = min(usable, usable * float(settings["initial_battery_soc"]))
    restricted = events = longest = current = viable_breaches = 0
    maximum_shortfall = residual_energy = constrained = shifted = discharged = demand_energy = 0.0
    timeline = []
    for point in points:
        baseline = max(0.0, float(point["import_mw"]) - float(point.get("onsite_generation_mw", 0)))
        declared_limit = float(settings["firm_import_mw"]) + float(settings["conditional_import_mw"])
        limit = max(0.0, float(point.get("connection_limit_mw", declared_limit * max(0.0, float(point.get("connection_limit_factor", 1))))))
        gross = max(0.0, baseline - limit)
        shiftable = min(float(point.get("flexible_load_mw", settings["shiftable_load_mw"])), float(settings["shiftable_load_mw"]))
        workload = min(gross, shiftable, max(0.0, baseline - float(settings["minimum_critical_load_mw"])))
        after_workload = gross - workload
        available_battery = soc * efficiency / duration
        battery = min(after_workload, float(settings["battery_power_mw"]), available_battery)
        used = battery * duration
        soc = max(0.0, soc - used / efficiency)
        headroom = max(0.0, limit - baseline)
        charge = min(0.0 if gross > 0 else headroom, float(settings["battery_power_mw"]), max(0.0, usable - soc) / (duration * efficiency))
        soc = min(usable, soc + charge * duration * efficiency)
        residual = max(0.0, after_workload - battery)
        if gross > 0:
            restricted += 1
            current += 1
            if current == 1:
                events += 1
            longest = max(longest, current)
        else:
            current = 0
        minimum_viable = settings.get("minimum_viable_import_mw")
        if minimum_viable is not None and limit < float(minimum_viable):
            viable_breaches += 1
        maximum_shortfall = max(maximum_shortfall, gross)
        constrained += gross * duration
        shifted += workload * duration
        discharged += used
        residual_energy += residual * duration
        demand_energy += baseline * duration
        timeline.append({
            "timestamp": point["timestamp"], "baseline_import_mw": _round(baseline),
            "connection_limit_mw": _round(limit), "workload_response_mw": _round(workload),
            "battery_response_mw": _round(battery), "battery_charge_mw": _round(charge),
            "residual_shortfall_mw": _round(residual), "battery_soc_mwh": _round(soc),
        })
    classification = ("fails_minimum_viable_capacity" if viable_breaches else
                      "feasible_with_constraints" if residual_energy > 0 else
                      "operator_validation_required" if restricted else "operationally_feasible")
    return {
        "calculation_version": "gridpulse-fca-dispatch-v1", "interval_minutes": minutes,
        "interval_count": len(points), "peak_baseline_import_mw": max(item["baseline_import_mw"] for item in timeline),
        "restricted_intervals": restricted, "restricted_hours": _round(restricted * duration),
        "restriction_events": events, "longest_restriction_hours": _round(longest * duration),
        "minimum_viable_breaches": viable_breaches, "maximum_shortfall_mw": _round(maximum_shortfall),
        "residual_unserved_mwh": _round(residual_energy), "constrained_energy_mwh": _round(constrained),
        "shifted_workload_mwh": _round(shifted), "battery_discharge_mwh": _round(discharged),
        "equivalent_battery_cycles": _round(discharged / battery_energy if battery_energy else 0),
        "demand_served_percent": _round((demand_energy - residual_energy) / demand_energy * 100 if demand_energy else 100),
        "estimated_exposure_eur": _round(residual_energy * float(settings["energy_value_eur_mwh"]) + discharged * float(settings["battery_degradation_eur_mwh"])),
        "classification": classification, "timeline": timeline,
        "warnings": ["Connection limits are declared inputs and not inferred available capacity."],
    }


def _profile(points: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    minutes = _interval_minutes(points)
    duration = minutes / 60
    totals = {key: 0.0 for key in ("requested_import", "requested_export", "served_import", "served_export")}
    restricted = 0
    window = settings.get("restriction_window")
    for point in points:
        event = datetime.fromisoformat(str(point["timestamp"]).replace("Z", "+00:00"))
        applies = True
        if window:
            hour = event.hour
            weekdays = window.get("weekdays", [])
            in_day = not weekdays or event.isoweekday() in weekdays
            start, end = int(window["start_hour"]), int(window["end_hour"])
            in_hour = start <= hour < end if start <= end else hour >= start or hour < end
            applies = in_day and in_hour
        active = settings.get("mode") != "unrestricted" and applies
        imported, exported = float(point["import_mw"]), float(point["export_mw"])
        import_limit = settings.get("max_import_mw") if active else None
        export_limit = settings.get("max_export_mw") if active else None
        served_import = min(imported, float(import_limit)) if import_limit is not None else imported
        served_export = min(exported, float(export_limit)) if export_limit is not None else exported
        restricted += int(served_import < imported or served_export < exported)
        totals["requested_import"] += imported * duration
        totals["requested_export"] += exported * duration
        totals["served_import"] += served_import * duration
        totals["served_export"] += served_export * duration
    constrained_import = totals["requested_import"] - totals["served_import"]
    constrained_export = totals["requested_export"] - totals["served_export"]
    return {
        "calculation_version": "gridpulse-fca-profile-v1", "interval_count": len(points),
        "interval_minutes": minutes, "covered_hours": len(points) * duration,
        "restricted_intervals": restricted, "restricted_hours": restricted * duration,
        "requested_import_mwh": _round(totals["requested_import"]),
        "requested_export_mwh": _round(totals["requested_export"]),
        "served_import_mwh": _round(totals["served_import"]),
        "served_export_mwh": _round(totals["served_export"]),
        "constrained_import_mwh": _round(constrained_import),
        "constrained_export_mwh": _round(constrained_export),
        "estimated_gross_impact_eur": _round((constrained_import + constrained_export) * float(settings.get("energy_value_eur_mwh", 0))),
    }


def run_fca_interval(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != FCA_INTERVAL_REQUEST_SCHEMA:
        raise ValueError("unsupported FCA interval request schema")
    points = request.get("points")
    settings = request.get("settings")
    if not isinstance(points, list) or not isinstance(settings, dict):
        raise TypeError("FCA points and settings are required")
    kind = str(request.get("analysis_kind", "dispatch"))
    if kind not in {"dispatch", "envelope_profile"}:
        raise ValueError("unsupported FCA interval analysis kind")
    result = _dispatch(points, settings) if kind == "dispatch" else _profile(points, settings)
    payload = {
        "schema_version": FCA_INTERVAL_RESULT_SCHEMA, "engine_version": ENGINE_VERSION,
        "input_fingerprint": _fingerprint(request), "capacity_claim": False,
        "automatic_live_dispatch_authorized": False, "result": result,
    }
    payload["result_fingerprint"] = _fingerprint(payload)
    return payload
