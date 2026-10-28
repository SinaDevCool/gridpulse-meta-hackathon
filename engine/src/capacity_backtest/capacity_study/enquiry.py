"""Truth-safe DSO/TSO enquiry package generated from a frozen capacity run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from capacity_backtest.storage import atomic_write

REQUESTED_OPERATOR_FIELDS = (
    "confirmed_pcc",
    "topology",
    "line_and_transformer_ratings",
    "nodal_loading_cases",
    "switch_and_tap_states",
    "committed_connections",
    "queue_and_reservations",
    "reviewed_contingency_set",
    "planned_and_unplanned_outages",
    "voltage_and_reactive_requirements",
    "protection_and_short_circuit_results",
    "harmonic_and_dynamic_requirements",
)


def build_enquiry_package(run_path: Path, destination: Path) -> Path:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("capacity_claim") is not False:
        raise ValueError("enquiry input must reject an operator-confirmed capacity claim")
    site = run["configuration"]["site"]
    package: dict[str, Any] = {
        "schema_version": "gridpulse-operator-enquiry-v1",
        "source_run_id": run["run_id"],
        "source_run_sha256": hashlib.sha256(run_path.read_bytes()).hexdigest(),
        "site_request": site,
        "pcc_hypotheses": run["pccs"],
        "screening_statistics": run["statistics"],
        "truth_class": run["truth_class"],
        "capacity_claim": False,
        "requested_operator_fields": REQUESTED_OPERATOR_FIELDS,
        "statement": "GridPulse screening estimate; not operator-confirmed connection capacity.",
    }
    atomic_write(
        destination / "enquiry.json",
        (json.dumps(package, indent=2, ensure_ascii=False) + "\n").encode(),
    )
    markdown = (
        "# GridPulse operator enquiry\n\n"
        + package["statement"]
        + "\n\n## Requested operator evidence\n\n"
        + "\n".join(f"- {field}" for field in REQUESTED_OPERATOR_FIELDS)
        + "\n"
    )
    atomic_write(destination / "enquiry.md", markdown.encode())
    return destination
