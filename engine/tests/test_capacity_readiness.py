from capacity_backtest.capacity_study.readiness import assess_capacity_readiness
from grid_data.network_study import StudyResult

from .test_capacity_study import network


class Provider:
    def run_base_case(self, _model):
        return StudyResult(
            "demonstration", "base_case", "fixture", converged=True, values={"passes": True}
        )


def test_readiness_requires_operator_operating_evidence() -> None:
    result = assess_capacity_readiness(network(), Provider())
    assert result.base_case_passed
    assert not result.capacity_ready
    assert "missing_confirmed_pcc" in result.blockers
