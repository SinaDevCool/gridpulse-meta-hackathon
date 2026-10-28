from dataclasses import replace

from capacity_backtest.territory.registry import (
    parse_mastr_operator_registry,
    reconcile_operator,
    select_registry_as_known,
)

XML = b"""<Export><Marktakteur><MastrNummer>SNB123</MastrNummer><Firmenname>Stromnetz Berlin GmbH</Firmenname><Marktfunktion>Stromnetzbetreiber</Marktfunktion><BdewCode>9901</BdewCode></Marktakteur><Marktakteur><MastrNummer>GEN1</MastrNummer><Firmenname>Generator</Firmenname><Marktfunktion>Anlagenbetreiber</Marktfunktion></Marktakteur></Export>"""


def test_mastr_registry_keeps_network_operators_and_matches_identifiers_first() -> None:
    release = parse_mastr_operator_registry(XML, source_id="mastr", published_at="2025-01-01T00:00:00Z",
                                            retrieved_at="2025-01-02T00:00:00Z")
    assert len(release.entries) == 1
    assert reconcile_operator(release.entries, mastr_number="SNB123").method == "mastr_number"
    assert reconcile_operator(release.entries, name="Stromnetz Berlin GmbH").confidence == .9
    assert reconcile_operator(release.entries, name="Generator").review_required


def test_registry_release_respects_evidence_cutoff_and_ambiguity() -> None:
    release = parse_mastr_operator_registry(XML, source_id="mastr", published_at="2025-01-01T00:00:00Z",
                                            retrieved_at="2025-01-02T00:00:00Z")
    assert not select_registry_as_known(release, "2025-01-01T12:00:00Z")
    assert select_registry_as_known(release, "2025-01-02T00:00:00Z")
    duplicate = replace(release.entries[0], operator_id="other")
    assert reconcile_operator((*release.entries, duplicate), mastr_number="SNB123").method == "ambiguous"
