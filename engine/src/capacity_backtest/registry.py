"""Machine-readable authoritative source registry."""

from __future__ import annotations

from pathlib import Path

import yaml

from .contracts import SourceDefinition, coerce_truth_class


def load_registry(config_dir: Path) -> list[SourceDefinition]:
    sources: list[SourceDefinition] = []
    seen: set[str] = set()
    for path in sorted(config_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in payload.get("sources", []):
            source = SourceDefinition(
                **{**raw, "truth_class": coerce_truth_class(raw["truth_class"])}
            )
            source.validate()
            if source.id in seen:
                raise ValueError(f"duplicate source id: {source.id}")
            seen.add(source.id)
            sources.append(source)
    if not sources:
        raise ValueError(f"no sources found under {config_dir}")
    return sources


def registry_by_id(config_dir: Path) -> dict[str, SourceDefinition]:
    return {source.id: source for source in load_registry(config_dir)}
