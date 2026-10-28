from datetime import datetime, timezone

import pytest

from capacity_backtest.capacity_study.flexibility_requirement import (
    OperatingTerms,
    build_flexibility_requirement,
)
from capacity_backtest.contracts import TruthClass
from capacity_backtest.domain.evidence import RunProvenance
from capacity_backtest.domain.results import CapacityEnvelopeResult


def capacity_result(*, firm=80.0, conditional=100.0, truth=TruthClass.PUBLIC_SCREENING):
    now = datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat()
    provenance = RunProvenance(
        run_id="run", created_at=now, evidence_cutoff="2026-01-01T00:00:00+00:00",
        code_version="test", assumption_set_id="a", solver_name="test", solver_version="1",
        input_hashes={"network": "a" * 64},
    )
    return CapacityEnvelopeResult(
        result_id="capacity-1", scenario_id="scenario", truth_class=truth,
        firm_capacity_mw=firm, conditional_capacity_mw=conditional,
        activatable_capacity_mw=None, confidence_level=0.9, binding_constraint="line",
        unknown_constraints=(), capacity_claim=False, provenance=provenance,
    )


def build(result, requested, **kwargs):
    return build_flexibility_requirement(
        result, site_id="site", pcc_id="pcc", requested_import_mw=requested,
        expected_provenance_fingerprint=result.provenance.fingerprint(), **kwargs,
    )


def test_reduction_below_firm_and_between_firm_and_conditional() -> None:
    assert build(capacity_result(), 70).required_reduction_mw == 0
    requirement = build(capacity_result(), 90)
    assert requirement.required_reduction_mw == 10
    assert requirement.feasible_within_conditional_envelope


def test_request_above_conditional_is_explicitly_infeasible() -> None:
    requirement = build(capacity_result(), 110)
    assert not requirement.feasible_within_conditional_envelope
    assert "requested_import_exceeds_conditional_envelope" in requirement.blockers


def test_unknown_terms_are_blockers_not_zeroes() -> None:
    requirement = build(capacity_result(), 90)
    assert requirement.response_time_seconds is None
    assert requirement.maximum_event_duration_minutes is None
    assert {"response_time_unknown", "maximum_event_duration_unknown"} <= set(requirement.blockers)


def test_provenance_mismatch_fails_closed() -> None:
    result = capacity_result()
    with pytest.raises(ValueError, match="provenance"):
        build_flexibility_requirement(
            result, site_id="site", pcc_id="pcc", requested_import_mw=90,
            expected_provenance_fingerprint="0" * 64,
        )


def test_lower_bound_is_preserved_conservatively() -> None:
    requirement = build(capacity_result(), 90, capacity_is_lower_bound=True)
    assert requirement.capacity_is_lower_bound
    assert requirement.conservative_required_reduction_mw == 90


def test_operating_terms_are_preserved() -> None:
    terms = OperatingTerms(response_time_seconds=30, maximum_event_duration_minutes=60)
    requirement = build(capacity_result(), 90, operating_terms=terms)
    assert requirement.response_time_seconds == 30
    assert not requirement.blockers
