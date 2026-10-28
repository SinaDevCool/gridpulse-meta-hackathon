from pathlib import Path

from capacity_backtest.territory.contracts import SiteLocation
from capacity_backtest.territory.pipeline import resolve_site_operator
from capacity_backtest.territory.registry import parse_mastr_operator_registry
from capacity_backtest.territory.reports import render_resolution_markdown
from capacity_backtest.territory.sources import ingest_territory_geojson

ROOT=Path(__file__).parent / "fixtures" / "territory"


def test_berlin_golden_resolves_geographic_dso_but_never_capacity(tmp_path) -> None:
    territories=ingest_territory_geojson((ROOT/"berlin-territory.geojson").read_bytes(),tmp_path/"release.json",
        source_id="fixture",source_url="https://example.test/fixture",licence="test-only",
        retrieved_at="2024-01-02T00:00:00Z")
    registry=parse_mastr_operator_registry((ROOT/"mastr-operators.xml").read_bytes(),source_id="mastr-fixture",
        published_at="2024-01-01T00:00:00Z",retrieved_at="2024-01-02T00:00:00Z")
    location=SiteLocation("berlin-dc",52.5,13.4,"address_rooftop","fixture","2024-01-01T00:00:00Z",
                          coordinate_accuracy_m=10)
    result=resolve_site_operator(location,territories,registry.entries,decision_time="2025-01-01T00:00:00Z",
        evidence_cutoff="2024-01-02T00:00:00Z",requested_mw=80,boundary_review_m=500)
    assert result["geographic_dso"] == "stromnetz-berlin-mastr"
    assert result["status"] == "validated_geographic_match"
    assert not result["physical_nodal_run_allowed"] and "No operator-assigned PCC" in result["limitations"]
    assert "Operator-confirmed claim allowed: **False**" in render_resolution_markdown(result)
