from __future__ import annotations

import ast
import importlib.metadata
from pathlib import Path

import yaml


def test_canonical_capacity_package_does_not_import_non_authoritative_demonstrations() -> None:
    package = Path(__file__).parents[1] / "src" / "capacity_backtest" / "capacity_study"
    prohibited = {
        "grid_data.synthetic_capacity",
        "grid_data.fifty_hertz_synthetic_capacity",
        "grid_data.fifty_hertz_regional_screening",
        "capacity_backtest.hourly_ac",
        "capacity_backtest.flex_study",
        "capacity_backtest.synthetic_operator",
    }
    violations = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in prohibited:
                violations.append(f"{path.name}:{node.module}")
    assert not violations


def test_every_registered_authority_is_unique_and_exists() -> None:
    root = Path(__file__).parents[1]
    registry = yaml.safe_load((root / "config/synthetic_component_ownership.yaml").read_text())
    assert registry["schema_version"] == "synthetic-component-ownership-v4"
    authorities = [item["authority"] for item in registry["components"].values()]
    assert len(authorities) == len(set(authorities))
    local = [path for path in authorities if not path.startswith("external:")]
    external = [path for path in authorities if path.startswith("external:")]
    assert all((root / path).is_file() for path in local)
    assert external
    assert importlib.metadata.version("gridpulse-grid-core").startswith("0.2.")


def test_non_authoritative_modules_are_not_registered_as_authorities() -> None:
    root = Path(__file__).parents[1]
    registry = yaml.safe_load((root / "config/synthetic_component_ownership.yaml").read_text())
    authorities = {item["authority"] for item in registry["components"].values()}
    assert authorities.isdisjoint(registry["non_authoritative_demonstrations"])


def test_repository_dependency_boundary_is_directional_and_documented() -> None:
    root = Path(__file__).parents[1]
    registry = yaml.safe_load((root / "config/synthetic_component_ownership.yaml").read_text())
    boundary = registry["repository_boundary"]
    assert boundary["dependency_order"] == [
        "gridpulse-grid-core",
        "gridpulse-capacity-backtest",
        "production-analytics-service",
        "production-web-ui",
    ]
    assert (root / boundary["production_integration"]).is_file()
    assert boundary["grid_core_distribution"] == "gridpulse-grid-core"


def test_grid_data_is_installed_and_not_copied_into_backtest_source() -> None:
    root = Path(__file__).parents[1]
    assert not any((root / "src" / "grid_data").glob("*.py"))
    assert importlib.metadata.version("gridpulse-grid-core").startswith("0.2.")


def test_capacity_engine_does_not_import_production_service_layer() -> None:
    root = Path(__file__).parents[1]
    package = root / "src" / "capacity_backtest"
    violations: list[str] = []
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "grid_data.api":
                violations.append(str(path.relative_to(root)))
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                "grid_data.api."
            ):
                violations.append(str(path.relative_to(root)))
            elif isinstance(node, ast.Import):
                if any(alias.name.startswith("grid_data.api") for alias in node.names):
                    violations.append(str(path.relative_to(root)))
    assert not violations
