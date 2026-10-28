from dataclasses import replace

from capacity_backtest.contracts import TruthClass
from capacity_backtest.domain.resources import FlexibilityPortfolio
from capacity_backtest.domain.scenario import StudyHorizon, StudyScenario
from capacity_backtest.territory.admissibility import evaluate_territory_admissibility
from capacity_backtest.territory.confirmation import ConfirmationAuthorization
from capacity_backtest.territory.contracts import ResponsibilityResult, SiteLocation, TerritoryMatch

SCENARIO = StudyScenario("s", "model", "pcc", "2025-01-01T00:00:00Z", StudyHorizon.CONNECTION_PLANNING,
    80, 40, .95, TruthClass.PUBLIC_SCREENING, FlexibilityPortfolio("f", ()), (), "forecast", "assumptions",
    site_location_id="site", territory_match_id="tm", responsibility_result_id="rr",
    operator_confirmation_id="confirmation", candidate_pcc_evidence_id="pcc-evidence")
LOCATION = SiteLocation("site",52.5,13.4,"address_rooftop","source","2024-01-01T00:00:00Z")
MATCH = TerritoryMatch("site","berlin","snb","matched","geojson",1,1000,(),False,("t",))
RESP = ResponsibilityResult("site","snb","snb","distribution","operator_confirmed",(),False,("c",))
AUTH = ConfirmationAuthorization(True,True,True,False,True,"study")


def test_screening_remains_allowed_without_pcc_but_physical_run_does_not() -> None:
    result=evaluate_territory_admissibility(SCENARIO,LOCATION,MATCH,RESP,None,
                                            network_operator_id="snb",candidate_pcc_id=None)
    assert result.public_screening_allowed and not result.physical_nodal_run_allowed


def test_confirmed_pcc_and_matching_network_unlock_physical_and_study_outcome() -> None:
    result=evaluate_territory_admissibility(SCENARIO,LOCATION,MATCH,RESP,AUTH,
                                            network_operator_id="snb",candidate_pcc_id="pcc")
    assert result.physical_nodal_run_allowed and result.operator_confirmed_claim_allowed
    conflict=evaluate_territory_admissibility(SCENARIO,LOCATION,MATCH,RESP,AUTH,
                                              network_operator_id="edis",candidate_pcc_id="pcc")
    assert not conflict.physical_nodal_run_allowed and "conflicts" in conflict.blockers[0]


def test_partial_real_site_references_are_rejected() -> None:
    try:
        replace(SCENARIO, territory_match_id=None).validate()
    except ValueError as error:
        assert "location, territory" in str(error)
    else:
        raise AssertionError("partial references must fail")
