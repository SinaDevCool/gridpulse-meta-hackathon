import pytest

from capacity_backtest.territory.contracts import TerritoryMatch
from capacity_backtest.territory.registry import RegistryMatch
from capacity_backtest.territory.responsibility import resolve_responsibility

MATCH = TerritoryMatch("site", "berlin", "snb", "matched", "geojson", 1, 1000, (), False, ("t",))
REGISTRY = RegistryMatch("snb", "mastr_number", 1, False)


def test_large_load_does_not_self_assign_tso() -> None:
    result = resolve_responsibility(MATCH, REGISTRY, requested_mw=500)
    assert result.candidate_connection_operator_id == "snb"
    assert result.candidate_connection_level == "distribution"
    assert result.review_required


def test_private_network_exception_requires_operator_study() -> None:
    result = resolve_responsibility(MATCH, REGISTRY, requested_mw=80,
                                    exception_flags=("closed_distribution_network",))
    assert result.status == "requires_operator_study" and result.candidate_connection_operator_id is None


def test_operator_assignment_requires_evidence() -> None:
    with pytest.raises(ValueError, match="requires evidence"):
        resolve_responsibility(MATCH, REGISTRY, requested_mw=80,
                               operator_assigned_connection_id="50hertz", operator_assigned_level="transmission")
    result = resolve_responsibility(MATCH, REGISTRY, requested_mw=80,
        operator_assigned_connection_id="50hertz", operator_assigned_level="transmission",
        operator_evidence_id="letter-1")
    assert result.status == "operator_confirmed" and not result.review_required
