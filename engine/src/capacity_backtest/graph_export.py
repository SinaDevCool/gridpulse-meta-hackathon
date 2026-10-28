"""Portable Neo4j-compatible graph export without requiring a live database in CI."""

from __future__ import annotations

import csv
from pathlib import Path

from grid_data.network_study import NetworkModelInput


def export_neo4j_csv(model: NetworkModelInput, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    node_path, edge_path = output / "nodes.csv", output / "relationships.csv"
    with node_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["node_id:ID", "voltage_kv", ":LABEL"])
        writer.writeheader()
        for bus in model.buses:
            writer.writerow({"node_id:ID": bus["id"], "voltage_kv": bus["vn_kv"], ":LABEL": "GridNode"})
    with edge_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[":START_ID", ":END_ID", "asset_id", ":TYPE"])
        writer.writeheader()
        for branch in model.branches:
            writer.writerow({":START_ID": branch["from_bus"], ":END_ID": branch["to_bus"], "asset_id": branch["id"], ":TYPE": "CONNECTED_TO"})
    return {"nodes": len(model.buses), "relationships": len(model.branches), "capacity_claim": False}
