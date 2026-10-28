from pathlib import Path

from capacity_backtest.regional_identity import load_operator_identities, match_operator

ROOT = Path(__file__).parents[1]


def test_published_operator_aliases_match_deterministically() -> None:
    identities = load_operator_identities(ROOT / "config/operator_identity.yaml")
    match = match_operator("E.DIS Netz", identities)
    assert match.canonical_id == "edis"
    assert match.confidence == 1
    assert match.review_required is False


def test_unknown_and_similarly_named_operator_is_quarantined() -> None:
    identities = load_operator_identities(ROOT / "config/operator_identity.yaml")
    match = match_operator("E.DIS Netzservice Nord GmbH", identities)
    assert match.canonical_id is None
    assert match.review_required is True
