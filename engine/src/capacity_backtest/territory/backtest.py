"""Historical evaluation of operator responsibility with leakage and confidence safety metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from capacity_backtest.domain.base import parse_aware_timestamp, require_non_empty

from .contracts import SiteLocation


@dataclass(frozen=True)
class HistoricalOperatorCase:
    case_id: str
    decision_time: str
    evidence_cutoff: str
    site_location: SiteLocation
    expected_geographic_dso_id: str | None
    expected_connection_operator_id: str | None
    expected_status: str

    def validate(self) -> None:
        require_non_empty(self.case_id, "case_id")
        decision = parse_aware_timestamp(self.decision_time, "decision_time")
        cutoff = parse_aware_timestamp(self.evidence_cutoff, "evidence_cutoff")
        if cutoff > decision:
            raise ValueError("historical case evidence cutoff follows decision")
        self.site_location.validate()


@dataclass(frozen=True)
class OperatorPrediction:
    case_id: str
    geographic_dso_id: str | None
    connection_operator_id: str | None
    status: str
    confidence: float
    evidence_timestamps: tuple[str, ...]

    def validate(self) -> None:
        require_non_empty(self.case_id, "case_id")
        if not 0 <= self.confidence <= 1:
            raise ValueError("prediction confidence must be in [0,1]")
        for value in self.evidence_timestamps:
            parse_aware_timestamp(value, "evidence_timestamp")


def evaluate_operator_backtest(
    cases: list[HistoricalOperatorCase], predictions: list[OperatorPrediction], *,
    confident_threshold: float = 0.9,
) -> dict[str, object]:
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("historical cases must be nonempty and unique")
    if len({row.case_id for row in predictions}) != len(predictions):
        raise ValueError("operator predictions must be unique")
    by_id = {row.case_id: row for row in predictions}
    rows = []
    exact = candidate_recall = incorrect_confident = uncovered = ambiguity = leakage = 0
    for case in cases:
        case.validate()
        prediction = by_id.get(case.case_id)
        if prediction is None:
            uncovered += 1
            rows.append({"case_id": case.case_id, "status": "missing_prediction"})
            continue
        prediction.validate()
        cutoff = parse_aware_timestamp(case.evidence_cutoff, "evidence_cutoff")
        leaked = any(parse_aware_timestamp(value, "evidence_timestamp") > cutoff for value in prediction.evidence_timestamps)
        leakage += leaked
        dso_correct = prediction.geographic_dso_id == case.expected_geographic_dso_id
        connection_correct = prediction.connection_operator_id == case.expected_connection_operator_id
        exact += dso_correct and connection_correct and prediction.status == case.expected_status
        candidate_recall += dso_correct or connection_correct
        wrong = not (dso_correct and connection_correct)
        incorrect_confident += wrong and prediction.confidence >= confident_threshold
        ambiguity += prediction.status in {"ambiguous", "boundary", "overlapping", "unresolved"}
        uncovered += prediction.status in {"uncovered", "historically_unavailable"}
        rows.append({**asdict(prediction), "dso_correct": dso_correct,
                     "connection_operator_correct": connection_correct, "leakage": leaked})
    total = len(cases)
    return {
        "schema_version": "gridpulse-operator-territory-backtest-v1",
        "case_count": total,
        "exact_accuracy": exact / total,
        "candidate_set_recall": candidate_recall / total,
        "incorrect_confident_match_rate": incorrect_confident / total,
        "ambiguity_rate": ambiguity / total,
        "uncovered_rate": uncovered / total,
        "historical_leakage_count": leakage,
        "release_gate_passed": incorrect_confident == 0 and leakage == 0,
        "rows": rows,
    }
