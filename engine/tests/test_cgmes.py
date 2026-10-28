import zipfile
from pathlib import Path

import pytest

from capacity_backtest.cgmes import inspect_cgmes_package


def write_package(path: Path, profiles: tuple[str, ...]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for profile in profiles:
            archive.writestr(f"model_{profile}.xml", "<rdf:RDF xmlns:rdf='urn:test'/>")


def test_cgmes_inventory_stays_operator_model_unvalidated(tmp_path: Path) -> None:
    path = tmp_path / "model.zip"
    write_package(path, ("EQ", "SSH", "TP", "SV"))
    result = inspect_cgmes_package(path)
    assert result.profiles == ("EQ", "SSH", "SV", "TP")
    assert result.truth_class == "operator_model_unvalidated"
    assert result.capacity_claim is False


def test_cgmes_inventory_rejects_missing_state_profile(tmp_path: Path) -> None:
    path = tmp_path / "model.zip"
    write_package(path, ("EQ", "SSH", "TP"))
    with pytest.raises(ValueError, match="SV"):
        inspect_cgmes_package(path)
