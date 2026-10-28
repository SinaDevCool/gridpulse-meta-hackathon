"""Generate a transparent evidence audit from the registry and sufficiency gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .quality import assess_source
from .registry import load_registry
from .sufficiency import berlin_public_evidence_assessment


def build_audit(config_dir: Path) -> dict[str, object]:
    sources = load_registry(config_dir)
    assessments = berlin_public_evidence_assessment()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "study_area": "Berlin",
        "decision": "Public evidence is insufficient for available-MW claims at grid nodes.",
        "permitted_outputs": [
            "published demand and allocation history",
            "constraint and reinforcement context",
            "experimental relative ranking with validation warnings",
        ],
        "prohibited_outputs": [
            "live nodal headroom",
            "connection feasibility",
            "capacity, cost, or delivery promises",
        ],
        "sources": [
            {
                "id": source.id,
                "publisher": source.publisher,
                "url": source.url,
                "truth_class": source.truth_class.value,
                "purposes": source.purposes,
                "prohibited_uses": source.prohibited_uses,
                "quality": [assess_source(source, role).as_dict() for role in source.purposes],
            }
            for source in sources
        ],
        "sufficiency": [assessment.as_dict() for assessment in assessments],
    }


def write_audit(config_dir: Path, json_path: Path, markdown_path: Path) -> None:
    audit = build_audit(config_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rows = [
        "# Berlin grid-capacity evidence audit",
        "",
        f"**Decision:** {audit['decision']}",
        "",
        "## Output sufficiency",
        "",
        "| Output | Status | Missing mandatory inputs |",
        "|---|---|---|",
    ]
    for item in audit["sufficiency"]:
        missing = ", ".join(item["missing_inputs"]) or "None"
        rows.append(f"| {item['output']} | {item['status']} | {missing} |")
    rows.extend(["", "## Registered sources", ""])
    for source in audit["sources"]:
        rows.append(
            f"- **{source['publisher']} — {source['id']}**: "
            f"{source['truth_class']}; prohibited for {', '.join(source['prohibited_uses'])}."
        )
    rows.extend(
        [
            "",
            "## Release boundary",
            "",
            (
                "No public, mapped, synthetic, congestion, allocation, or reinforcement record "
                "is reported as available connection capacity. Unknown information remains unknown."
            ),
        ]
    )
    markdown_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
