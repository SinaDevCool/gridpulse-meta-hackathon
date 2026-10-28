from dataclasses import replace

import pytest

from capacity_backtest.territory.confirmation import authorize_confirmation
from capacity_backtest.territory.contracts import (
    OperatorResponsibilityConfirmation,
    ResponsibilityResult,
)

RESPONSIBILITY = ResponsibilityResult("site", "snb", "snb", "distribution", "operator_confirmed", (), False, ("letter",))
BASE = OperatorResponsibilityConfirmation("c", "site", "snb", "snb-registry", "responsible_operator",
    "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "a"*64, "letter.pdf", "portal", "reviewed")


def test_territory_or_responsibility_confirmation_cannot_create_capacity() -> None:
    result = authorize_confirmation(BASE, RESPONSIBILITY, as_of="2025-02-01T00:00:00Z", expected_site_id="site")
    assert result.responsibility_confirmed and not result.pcc_confirmed and not result.capacity_claim_allowed


def test_study_scope_requires_pcc_and_can_authorize_operator_outcome_only() -> None:
    confirmation = replace(BASE, confirmation_scope="connection_study_outcome", candidate_pcc_id="pcc")
    result = authorize_confirmation(confirmation, RESPONSIBILITY, as_of="2025-02-01T00:00:00Z", expected_site_id="site")
    assert result.pcc_confirmed and result.study_outcome_confirmed and result.capacity_claim_allowed


def test_expired_or_wrong_operator_confirmation_fails_closed() -> None:
    expired = replace(BASE, valid_to="2025-02-01T00:00:00Z")
    assert not authorize_confirmation(expired, RESPONSIBILITY, as_of="2025-02-01T00:00:00Z", expected_site_id="site").responsibility_confirmed
    with pytest.raises(ValueError, match="conflicts"):
        authorize_confirmation(replace(BASE, operator_id="edis"), RESPONSIBILITY,
                               as_of="2025-01-02T00:00:00Z", expected_site_id="site")
