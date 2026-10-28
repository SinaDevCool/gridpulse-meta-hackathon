from dataclasses import replace

import pytest

from capacity_backtest.territory.contracts import (
    OperatorResponsibilityConfirmation,
    SiteLocation,
    TerritoryMatch,
)


def test_location_and_match_contracts_fail_closed() -> None:
    location = SiteLocation("site", 52.5, 13.4, "address_rooftop", "bkg", "2025-01-01T00:00:00Z")
    location.validate()
    with pytest.raises(ValueError, match="coordinates"):
        replace(location, latitude=100).validate()
    with pytest.raises(ValueError, match="requires territory"):
        TerritoryMatch("site", None, None, "matched", "polygon", 1, 10).validate()


def test_pcc_confirmation_requires_reviewed_hashed_document() -> None:
    confirmation = OperatorResponsibilityConfirmation(
        "c1", "site", "snb", "registry-snb", "candidate_pcc_assigned",
        "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "a" * 64,
        "operator-letter.pdf", "operator portal", "reviewed", candidate_pcc_id="pcc-1",
    )
    confirmation.validate()
    with pytest.raises(ValueError, match="candidate_pcc_id"):
        replace(confirmation, candidate_pcc_id=None).validate()
