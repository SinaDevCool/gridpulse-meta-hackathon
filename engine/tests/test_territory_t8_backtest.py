from capacity_backtest.territory.backtest import (
    HistoricalOperatorCase,
    OperatorPrediction,
    evaluate_operator_backtest,
)
from capacity_backtest.territory.contracts import SiteLocation

LOCATION = SiteLocation("site", 52.5, 13.4, "address_rooftop", "source", "2024-01-01T00:00:00Z")


def test_historical_backtest_measures_accuracy_and_passes_safe_release() -> None:
    case=HistoricalOperatorCase("c","2025-01-02T00:00:00Z","2025-01-01T00:00:00Z",LOCATION,"snb","snb","matched")
    prediction=OperatorPrediction("c","snb","snb","matched",.95,("2025-01-01T00:00:00Z",))
    result=evaluate_operator_backtest([case],[prediction])
    assert result["exact_accuracy"] == 1 and result["release_gate_passed"]


def test_confident_error_and_future_evidence_fail_release() -> None:
    case=HistoricalOperatorCase("c","2025-01-02T00:00:00Z","2025-01-01T00:00:00Z",LOCATION,"snb","snb","matched")
    prediction=OperatorPrediction("c","edis","edis","matched",.99,("2025-01-02T00:00:00Z",))
    result=evaluate_operator_backtest([case],[prediction])
    assert result["incorrect_confident_match_rate"] == 1
    assert result["historical_leakage_count"] == 1 and not result["release_gate_passed"]
