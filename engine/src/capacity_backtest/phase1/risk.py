"""Risk-limiting capacity policies and chronological out-of-sample evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from capacity_backtest.domain import ForecastDistribution, NetworkEnvelope


class RiskPolicy(str, Enum):
    STATIC_MARGIN = "static_margin"
    FORECAST_QUANTILE = "forecast_quantile"
    CHANCE_CONSTRAINED = "chance_constrained"
    CVAR = "cvar"
    DISTRIBUTIONALLY_ROBUST = "distributionally_robust"
    PERFECT_FORESIGHT = "perfect_foresight_oracle"


@dataclass(frozen=True)
class RiskPolicyResult:
    policy: RiskPolicy
    admitted_capacity_mw: tuple[float, ...]
    unsafe_overstatement_hours: int
    violation_probability: float
    unserved_mwh: float
    utilized_mwh: float
    conservatism_mwh: float
    calibration_error: float
    oracle: bool = False


def _forecast_quantile(point, probability: float) -> float:
    labels = sorted((float(label), label) for label in point.quantiles_mw)
    return point.quantiles_mw[min(labels, key=lambda item: abs(item[0] - probability))[1]]


def _admission(
    policy: RiskPolicy,
    point,
    physical_limit: float,
    actual: float,
    confidence: float,
    static_margin_fraction: float,
) -> float:
    if policy == RiskPolicy.PERFECT_FORESIGHT:
        return min(physical_limit, actual)
    if policy == RiskPolicy.STATIC_MARGIN:
        return physical_limit * (1 - static_margin_fraction)
    upper = _forecast_quantile(point, confidence)
    if policy == RiskPolicy.FORECAST_QUANTILE:
        return min(physical_limit, upper)
    residual_risk = max(0.0, upper - point.mean_mw)
    if policy == RiskPolicy.CHANCE_CONSTRAINED:
        return max(0.0, physical_limit - residual_risk)
    tail = [value for label, value in point.quantiles_mw.items() if float(label) >= confidence]
    cvar_tail = sum(tail) / len(tail) if tail else upper
    if policy == RiskPolicy.CVAR:
        return max(0.0, physical_limit - max(0.0, cvar_tail - point.mean_mw))
    robust_error = max(abs(value - point.mean_mw) for value in point.quantiles_mw.values())
    return max(0.0, physical_limit - robust_error * 1.25)


def backtest_risk_policies(
    actual_demand_mw: list[float],
    forecast: ForecastDistribution,
    envelope: NetworkEnvelope,
    *,
    confidence: float = 0.9,
    static_margin_fraction: float = 0.1,
) -> dict[str, object]:
    forecast.validate()
    envelope.validate()
    if tuple(point.timestamp for point in forecast.points) != envelope.timestamps:
        raise ValueError("risk backtest inputs must be timestamp aligned")
    if len(actual_demand_mw) != len(forecast.points) or not actual_demand_mw:
        raise ValueError("actual demand must align with the forecast")
    if any(value < 0 for value in actual_demand_mw):
        raise ValueError("actual demand cannot be negative")
    if not 0 < confidence < 1 or not 0 <= static_margin_fraction < 1:
        raise ValueError("invalid risk policy parameters")

    results = []
    limits = [min(n0, n1) for n0, n1 in zip(envelope.n0_import_mw, envelope.n1_import_mw)]
    for policy in RiskPolicy:
        admitted = [
            _admission(policy, point, limit, actual, confidence, static_margin_fraction)
            for point, limit, actual in zip(forecast.points, limits, actual_demand_mw)
        ]
        delivered = [min(actual, allowance) for actual, allowance in zip(actual_demand_mw, admitted)]
        service_shortfalls = [
            actual > allowance + 1e-9
            for actual, allowance in zip(actual_demand_mw, admitted)
        ]
        unsafe_overstatements = [
            allowance > limit + 1e-9 for allowance, limit in zip(admitted, limits)
        ]
        predicted_tail = 1 - confidence if policy != RiskPolicy.PERFECT_FORESIGHT else 0.0
        observed = sum(service_shortfalls) / len(service_shortfalls)
        results.append(
            RiskPolicyResult(
                policy=policy,
                admitted_capacity_mw=tuple(admitted),
                unsafe_overstatement_hours=sum(unsafe_overstatements),
                violation_probability=observed,
                unserved_mwh=sum(max(0.0, actual - allowance) for actual, allowance in zip(actual_demand_mw, admitted)),
                utilized_mwh=sum(delivered),
                conservatism_mwh=sum(max(0.0, limit - allowance) for limit, allowance in zip(limits, admitted)),
                calibration_error=abs(observed - predicted_tail),
                oracle=policy == RiskPolicy.PERFECT_FORESIGHT,
            )
        )
    non_oracle = [item for item in results if not item.oracle]
    safe = [item for item in non_oracle if item.violation_probability <= 1 - confidence + 1e-12]
    recommended = max(safe, key=lambda item: item.utilized_mwh, default=min(non_oracle, key=lambda item: item.violation_probability))
    return {
        "schema_version": "gridpulse-risk-limiting-backtest-v1",
        "confidence": confidence,
        "truth_class": envelope.truth_class.value,
        "capacity_claim": False,
        "recommended_policy": recommended.policy.value,
        "results": [
            {
                "policy": item.policy.value,
                "admitted_capacity_mw": list(item.admitted_capacity_mw),
                "unsafe_overstatement_hours": item.unsafe_overstatement_hours,
                "violation_probability": item.violation_probability,
                "unserved_mwh": item.unserved_mwh,
                "utilized_mwh": item.utilized_mwh,
                "conservatism_mwh": item.conservatism_mwh,
                "calibration_error": item.calibration_error,
                "oracle": item.oracle,
            }
            for item in results
        ],
        "release_gate_passed": bool(safe),
        "release_gate_reason": "At least one non-oracle policy meets the empirical risk limit." if safe else "No non-oracle policy meets the empirical risk limit.",
    }
