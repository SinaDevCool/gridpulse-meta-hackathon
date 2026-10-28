"""Static enforcement of the read-only adapter boundary."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AdapterSafetyAssessment:
    passed: bool
    inspected_files: int
    violations: tuple[str, ...]


def assess_adapter_safety(adapter_root: Path) -> AdapterSafetyAssessment:
    prohibited_imports = {"capacity_backtest.phase3.commands", "subprocess", "socket"}
    prohibited_calls = {"post", "put", "patch", "delete", "write", "send", "issue"}
    violations = []
    files = sorted(path for path in adapter_root.glob("*.py") if path.name != "safety.py")
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in prohibited_imports:
                violations.append(f"{path.name}:prohibited_import:{node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in prohibited_imports:
                        violations.append(f"{path.name}:prohibited_import:{alias.name}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.lower() in prohibited_calls
            ):
                violations.append(f"{path.name}:prohibited_call:{node.func.attr}")
    return AdapterSafetyAssessment(not violations, len(files), tuple(violations))
