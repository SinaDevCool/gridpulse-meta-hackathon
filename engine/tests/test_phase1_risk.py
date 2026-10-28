from __future__ import annotations

from capacity_backtest.contracts import TruthClass
from capacity_backtest.domain import ForecastDistribution, ForecastPoint, NetworkEnvelope
from capacity_backtest.phase1.risk import RiskPolicy, backtest_risk_policies


def inputs():
    stamps = tuple(f"2026-01-01T{hour:02d}:00:00+00:00" for hour in range(1, 7))
    forecast = ForecastDistribution(
        forecast_id="risk-f1",
        issued_at="2026-01-01T00:00:00+00:00",
        component="total_site_load",
        points=tuple(ForecastPoint(stamp, 50, {"0.1": 45, "0.5": 50, "0.9": 55}) for stamp in stamps),
        model_version="fixture",
    )
    envelope = NetworkEnvelope(
        envelope_id="risk-env",
        network_model_id="n-1",
        candidate_bus_id="bus-1",
        timestamps=stamps,
        n0_import_mw=(70,) * 6,
        n1_import_mw=(60,) * 6,
        truth_class=TruthClass.SYNTHETIC_BENCHMARK,
    )
    return forecast, envelope


def test_risk_backtest_compares_all_policies_and_oracle() -> None:
    forecast, envelope = inputs()
    result = backtest_risk_policies([48, 52, 54, 58, 61, 49], forecast, envelope)
    assert len(result["results"]) == len(RiskPolicy)
    oracle = next(row for row in result["results"] if row["oracle"])
    assert oracle["unsafe_overstatement_hours"] == 0
    assert result["capacity_claim"] is False
    assert result["recommended_policy"] != RiskPolicy.PERFECT_FORESIGHT.value


def test_risk_backtest_rejects_timestamp_misalignment() -> None:
    forecast, envelope = inputs()
    object.__setattr__(envelope, "timestamps", tuple(reversed(envelope.timestamps)))
    try:
        backtest_risk_policies([50] * 6, forecast, envelope)
    except ValueError as error:
        assert "chronological" in str(error) or "aligned" in str(error)
    else:
        raise AssertionError("misaligned inputs were accepted")
