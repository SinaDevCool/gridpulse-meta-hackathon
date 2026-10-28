from __future__ import annotations

import json
from pathlib import Path

import pytest

from capacity_backtest.contracts import TruthClass
from capacity_backtest.phase1.ac_envelope import OperatingState, run_ac_envelope_study
from grid_data.network_study import NetworkModelInput, StudyResult

GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_phase1_cases.json").read_text(encoding="utf-8")
)["ac"]


class FakeProvider:
    def calculate_import_capacity(self, _model):
        return StudyResult(
            status="demonstration",
            study_type="capacity",
            provider="golden",
            converged=True,
            values={
                "base_case_capacity_mw": GOLDEN["base_case_capacity_mw"],
                "firm_import_capacity_mw": GOLDEN["firm_import_capacity_mw"],
                "binding_case": "line-outage",
                "binding_constraint": "line_thermal_loading",
                "capacity_is_lower_bound": False,
                "search_tolerance_mw": 0.1,
            },
        )


def model() -> NetworkModelInput:
    return NetworkModelInput(
        buses=[{"id": "bus-1"}], branches=[], transformers=[], loads=[], generators=[],
        switches=[], contingencies=[], connection_bus="bus-1", study_year=2026,
        provenance={"source_url": "fixture://phase1", "license": "test"},
        model_id="network-1", validation_class="synthetic_demonstration",
    )


def test_ac_study_builds_reservation_adjusted_n0_n1_envelope() -> None:
    states = [OperatingState("2026-01-01T01:00:00+00:00", 20, reserved_capacity_mw=5)]
    result = run_ac_envelope_study(
        model(), states, FakeProvider(), power_factor=0.96,
        truth_class=TruthClass.SYNTHETIC_BENCHMARK, envelope_id="env-1",
    )
    assert result.physics_verified
    assert result.envelope.n0_import_mw == (GOLDEN["expected_n0_mw"],)
    assert result.envelope.n1_import_mw == (GOLDEN["expected_n1_mw"],)
    assert result.states[0].reactive_power_mvar > 0


def test_ac_study_rejects_non_chronological_states() -> None:
    states = [
        OperatingState("2026-01-01T02:00:00+00:00", 20),
        OperatingState("2026-01-01T01:00:00+00:00", 20),
    ]
    with pytest.raises(ValueError, match="chronological"):
        run_ac_envelope_study(
            model(), states, FakeProvider(), power_factor=0.96,
            truth_class=TruthClass.SYNTHETIC_BENCHMARK, envelope_id="env-1",
        )
