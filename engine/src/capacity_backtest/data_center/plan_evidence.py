"""Plan-specific physical margins; observations, never causal solver explanations."""

from .acceptance import accepted_optimization


def plan_evidence(inputs: dict, result) -> dict:
    if not accepted_optimization(result):
        return {
            "basis": "canonical_physical_replay",
            "available": False,
            "findings": [],
            "causal_binding_constraints_assessed": False,
        }
    facility = inputs["facility"]
    target = inputs["policy"].operating_target_mw
    points = result.facility.points
    peak = max(points, key=lambda p: p.grid_import_mw)
    findings = [
        {
            "code": "peak_import_margin",
            "asset_id": facility.facility_id,
            "interval_index": peak.interval_index,
            "value": facility.import_limits(len(points))[peak.interval_index] - peak.grid_import_mw,
            "unit": "MW",
            "source_field": "facility.points.grid_import_mw",
        }
    ]
    if target is not None:
        findings.append(
            {
                "code": "peak_target_margin",
                "asset_id": facility.facility_id,
                "interval_index": peak.interval_index,
                "value": (inputs["policy"].operating_target_profile_mw or (target,) * len(points))[
                    peak.interval_index
                ]
                - peak.grid_import_mw,
                "unit": "MW",
                "source_field": "facility.points.grid_import_mw",
            }
        )
    for config, trajectory in zip(inputs["batteries"], result.battery_trajectories):
        reserve = max(
            config.minimum_reserve_mwh,
            config.critical_load_mw
            * config.backup_autonomy_minutes
            / 60
            / config.discharge_efficiency,
        )
        index, point = min(enumerate(trajectory.points), key=lambda item: item[1].soc_mwh)
        findings.append(
            {
                "code": "minimum_battery_reserve_margin",
                "asset_id": config.resource_id,
                "interval_index": index,
                "value": point.soc_mwh - config.soc_uncertainty_mwh - reserve,
                "unit": "MWh",
                "source_field": "battery_trajectories.points.soc_mwh",
            }
        )
    return {
        "basis": "canonical_physical_replay",
        "available": True,
        "findings": findings,
        "causal_binding_constraints_assessed": False,
    }
