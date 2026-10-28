"""Build a linked synthetic operator package without duplicating AC calculations."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .backtest import BenchmarkRecord, synthetic_network_families
from .contracts import TruthClass, coerce_truth_class
from .storage import atomic_write

SCHEMA_VERSION = "synthetic-operator-package-v1"
TRUTH_CLASS = "synthetic_benchmark"
SITE_SCENARIOS_MW = (10.0, 25.0, 50.0, 100.0, 200.0)
REQUIRED_TABLES = {
    "network_assets",
    "hourly_operating_states",
    "outages",
    "queue_requests",
    "connection_study_outcomes",
    "flexibility_contracts",
}


@dataclass(frozen=True)
class SyntheticOperatorConfig:
    start_at: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
    hours: int = 8760
    requests_per_node: int = 4
    seed_version: str = "grid-care-ai-synthetic-operator-v1"

    def validate(self) -> None:
        if self.start_at.tzinfo is None or self.start_at.utcoffset() is None:
            raise ValueError("synthetic start_at must be timezone-aware")
        if self.hours < 1 or self.hours > 8784:
            raise ValueError("synthetic operating period must be between 1 and 8784 hours")
        if self.requests_per_node < 1:
            raise ValueError("at least one synthetic request per node is required")


def _stable_fraction(*parts: object) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


@lru_cache(maxsize=4)
def _simbench_hourly_factors(hours: int) -> tuple[tuple[float, ...], dict[str, str]]:
    try:
        import simbench  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("the SimBench study dependency is required") from error
    column = "BL-H_pload"
    quarter_hour = simbench.get_all_simbench_profiles(0)["load"][column]
    available_hours = len(quarter_hour) // 4
    if hours > available_hours:
        raise ValueError("requested hours exceed the SimBench reference profile")
    raw = [
        sum(float(quarter_hour.iloc[hour * 4 + offset]) for offset in range(4)) / 4
        for hour in range(hours)
    ]
    # Keep a non-zero critical-demand floor while retaining the reference profile shape.
    factors = tuple(0.65 + 0.35 * value for value in raw)
    profile_hash = hashlib.sha256(json.dumps(factors, separators=(",", ":")).encode()).hexdigest()
    return factors, {
        "profile_source": "SimBench scenario 0 BL-H_pload aggregated from 15-minute means",
        "simbench_version": version("simbench"),
        "profile_sha256": profile_hash,
    }


def _records_by_case(records: list[BenchmarkRecord]) -> dict[tuple[str, str, str], float]:
    result = {
        (item.network_id, item.node_id, item.security_case): item.truth_capacity_mw
        for item in records
        if item.scenario == "annual_median"
    }
    if not result:
        raise ValueError("annual_median benchmark records are required")
    for network_id, node_id, _security in result:
        if (network_id, node_id, "n_0") not in result or (network_id, node_id, "n_1") not in result:
            raise ValueError("paired synthetic N-0 and N-1 records are required")
    return result


def network_asset_rows(network_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    """Reuse the benchmark families; do not create a second topology implementation."""
    for model in synthetic_network_families():
        if network_ids is not None and model.model_id not in network_ids:
            continue
        for bus in model.buses:
            yield {
                "network_id": model.model_id,
                "asset_id": str(bus["id"]),
                "asset_type": "bus",
                "from_bus": None,
                "to_bus": None,
                "nominal_voltage_kv": float(bus["vn_kv"]),
                "normal_rating_value": None,
                "emergency_rating_value": None,
                "rating_unit": None,
                "assumption_id": "berlin-public-anchor-synthetic-electrical-node",
                "truth_class": TRUTH_CLASS,
                "capacity_claim": False,
            }
        for branch in model.branches:
            normal = float(branch["max_i_ka"])
            yield {
                "network_id": model.model_id,
                "asset_id": str(branch["id"]),
                "asset_type": "line",
                "from_bus": str(branch["from_bus"]),
                "to_bus": str(branch["to_bus"]),
                "nominal_voltage_kv": 110.0,
                "normal_rating_value": normal,
                "emergency_rating_value": round(normal * 1.10, 6),
                "rating_unit": "kA",
                "assumption_id": str(branch.get("assumption_id", "synthetic-family-rating")),
                "truth_class": TRUTH_CLASS,
                "capacity_claim": False,
            }


def hourly_operating_rows(
    records: list[BenchmarkRecord],
    config: SyntheticOperatorConfig,
    demand_factors: tuple[float, ...],
    profile_metadata: dict[str, str],
) -> Iterator[dict[str, Any]]:
    """Produce annual mock demand/envelopes; no unsolved asset loading is invented."""
    paired = _records_by_case(records)
    cases = sorted({(network, node) for network, node, _security in paired})
    for hour in range(config.hours):
        timestamp = config.start_at + timedelta(hours=hour)
        seasonal = 0.5 + 0.5 * math.cos(2 * math.pi * hour / max(config.hours, 1))
        stress = demand_factors[hour]
        derating = 0.03 * stress + 0.06 * seasonal
        for network_id, node_id in cases:
            n0 = paired[(network_id, node_id, "n_0")]
            n1 = paired[(network_id, node_id, "n_1")]
            base = 7.0 + 10.0 * _stable_fraction(config.seed_version, network_id, node_id)
            yield {
                "timestamp": timestamp.isoformat(),
                "network_id": network_id,
                "bus_id": node_id,
                "synthetic_demand_mw": round(base * stress, 6),
                "synthetic_generation_mw": 0.0,
                "demand_profile_source": profile_metadata["profile_source"],
                "demand_profile_sha256": profile_metadata["profile_sha256"],
                "synthetic_n0_envelope_mw": round(max(0.0, n0 * (1 - derating)), 6),
                "synthetic_n1_envelope_mw": round(max(0.0, n1 * (1 - derating * 1.15)), 6),
                "asset_loading_percent": None,
                "switch_state": "synthetic_default_closed",
                "loading_limitation": "No hourly AC branch flow was solved; asset loading remains null.",
                "truth_class": TRUTH_CLASS,
                "capacity_claim": False,
            }


def outage_rows(
    config: SyntheticOperatorConfig, network_ids: set[str] | None = None
) -> Iterator[dict[str, Any]]:
    for family_index, model in enumerate(synthetic_network_families(), start=1):
        if network_ids is not None and model.model_id not in network_ids:
            continue
        for asset_index, branch in enumerate(model.branches):
            starts_at = config.start_at + timedelta(days=14 + asset_index * 9 + family_index)
            event_id = f"mock-outage-{family_index:02d}-{asset_index + 1:03d}"
            published_at = starts_at - timedelta(days=21)
            common = {
                "event_id": event_id,
                "network_id": model.model_id,
                "asset_id": str(branch["id"]),
                "starts_at": starts_at.isoformat(),
                "planned": True,
                "availability_percent": 0.0,
                "reason": "synthetic_planned_maintenance",
                "truth_class": TRUTH_CLASS,
                "capacity_claim": False,
            }
            yield {
                **common,
                "revision": 1,
                "published_at": published_at.isoformat(),
                "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
                "status": "scheduled",
            }
            yield {
                **common,
                "revision": 2,
                "published_at": (published_at + timedelta(days=7)).isoformat(),
                "ends_at": (starts_at + timedelta(hours=6)).isoformat(),
                "status": "revised",
            }


def _queue_and_outcomes(
    records: list[BenchmarkRecord],
    config: SyntheticOperatorConfig,
    outages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paired = _records_by_case(records)
    cases = sorted({(network, node) for network, node, _security in paired})
    reservations: dict[tuple[str, str], float] = {case: 0.0 for case in cases}
    requests: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    sequence = 0
    for round_index in range(config.requests_per_node):
        for network_id, node_id in cases:
            sequence += 1
            submitted = config.start_at + timedelta(days=7 * sequence)
            requested = SITE_SCENARIOS_MW[
                int(_stable_fraction(config.seed_version, network_id, node_id, round_index) * 5) % 5
            ]
            request_id = f"mock-request-{sequence:05d}"
            decision_at = submitted + timedelta(days=30)
            known_outages = sorted(
                {
                    row["event_id"]
                    for row in outages
                    if row["network_id"] == network_id
                    and datetime.fromisoformat(row["published_at"])
                    <= decision_at
                    <= datetime.fromisoformat(row["starts_at"]) + timedelta(days=365)
                }
            )
            reserved_before = reservations[(network_id, node_id)]
            synthetic_limit = paired[(network_id, node_id, "n_1")]
            residual = max(0.0, synthetic_limit - reserved_before)
            if requested <= residual:
                decision = "approved_firm"
                firm, conditional = requested, 0.0
            elif residual >= max(5.0, requested * 0.35):
                decision = "conditional_offer"
                firm, conditional = 0.0, round(residual, 6)
            else:
                decision = "rejected_synthetic_constraint"
                firm = conditional = 0.0
            reservations[(network_id, node_id)] += firm + conditional
            request = {
                "request_id": request_id,
                "network_id": network_id,
                "requested_bus": node_id,
                "submitted_at": submitted.isoformat(),
                "target_year": submitted.year + 2,
                "requested_mw": requested,
                "requested_mva": round(requested / 0.96, 6),
                "power_factor": 0.96,
                "service_type": "firm_or_conditional",
                "queue_status": "synthetic_decided",
                "reserved_before_mw": round(reserved_before, 6),
                "truth_class": TRUTH_CLASS,
                "capacity_claim": False,
            }
            outcome = {
                "request_id": request_id,
                "network_id": network_id,
                "studied_bus": node_id,
                "decision_at": decision_at.isoformat(),
                "decision": decision,
                "firm_mw_offered": firm,
                "conditional_mw_offered": conditional,
                "binding_constraint": next(
                    item.binding_constraint
                    for item in records
                    if item.network_id == network_id
                    and item.node_id == node_id
                    and item.scenario == "annual_median"
                    and item.security_case == "n_1"
                ),
                "binding_contingency": "synthetic_n1_envelope",
                "known_outage_ids_at_decision": known_outages,
                "security_basis": "synthetic_n1_with_publication_aware_mock_outage_schedule",
                "reinforcement_required": decision == "rejected_synthetic_constraint",
                "expected_delivery_at": (
                    submitted + timedelta(days=365 * 4)
                    if decision == "rejected_synthetic_constraint"
                    else submitted + timedelta(days=365)
                ).isoformat(),
                "reservation_after_mw": round(reservations[(network_id, node_id)], 6),
                "available_capacity_mw": None,
                "truth_class": TRUTH_CLASS,
                "capacity_claim": False,
            }
            requests.append(request)
            outcomes.append(outcome)
    return requests, outcomes


def flexibility_contract_rows() -> Iterator[dict[str, Any]]:
    for site_mw in SITE_SCENARIOS_MW:
        yield {
            "contract_id": f"mock-flex-{int(site_mw):03d}mw",
            "site_load_mw": site_mw,
            "critical_load_mw": site_mw * 0.8,
            "shiftable_load_mw": site_mw * 0.2,
            "maximum_interruptible_fraction": 0.1,
            "maximum_interruption_hours": 4,
            "annual_constrained_hour_budget": 120,
            "battery_power_mw": site_mw * 0.25,
            "battery_energy_mwh": site_mw,
            "minimum_reserve_soc_fraction": 0.1,
            "recovery_deadline_hours": 24,
            "ramp_limit_mw_per_hour": site_mw * 0.5,
            "backup_generation_mw": 0.0,
            "truth_class": TRUTH_CLASS,
            "capacity_claim": False,
        }


def validate_chronological_tables(
    outages: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> None:
    request_by_id = {row["request_id"]: row for row in requests}
    if len(request_by_id) != len(requests) or len(outcomes) != len(requests):
        raise ValueError("synthetic queue and outcomes require unique one-to-one identities")
    if {row["request_id"] for row in outcomes} != set(request_by_id):
        raise ValueError("synthetic outcomes must match the request population")
    for outcome in outcomes:
        request = request_by_id[outcome["request_id"]]
        if datetime.fromisoformat(outcome["decision_at"]) <= datetime.fromisoformat(
            request["submitted_at"]
        ):
            raise ValueError("synthetic decisions must occur after submission")
        if outcome["available_capacity_mw"] is not None or outcome["capacity_claim"] is not False:
            raise ValueError("synthetic outcomes cannot make an available-capacity claim")
    revisions: dict[str, list[dict[str, Any]]] = {}
    for outage in outages:
        revisions.setdefault(outage["event_id"], []).append(outage)
    for event in revisions.values():
        ordered = sorted(event, key=lambda row: row["revision"])
        if [row["revision"] for row in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("synthetic outage revisions must be contiguous")
        publications = [datetime.fromisoformat(row["published_at"]) for row in ordered]
        if publications != sorted(publications):
            raise ValueError("synthetic outage revisions must be publication ordered")


def _write_gzip_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
    ):
        for row in rows:
            compressed.write(
                (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
            )
            count += 1
    content = path.read_bytes()
    return count, hashlib.sha256(content).hexdigest(), len(content)


def build_synthetic_operator_package(
    records: list[BenchmarkRecord],
    data_root: Path,
    work_root: Path,
    config: SyntheticOperatorConfig | None = None,
) -> dict[str, Any]:
    config = config or SyntheticOperatorConfig()
    config.validate()
    if not records or any(
        coerce_truth_class(item.validation_class) != TruthClass.SYNTHETIC_BENCHMARK
        for item in records
    ):
        raise ValueError("only synthetic benchmark truth records may build this package")
    network_ids = {item.network_id for item in records}
    model_buses = {
        model.model_id: {str(bus["id"]) for bus in model.buses}
        for model in synthetic_network_families()
    }
    if network_ids - set(model_buses):
        raise ValueError("benchmark records contain an unknown synthetic network family")
    if any(item.node_id not in model_buses[item.network_id] for item in records):
        raise ValueError("benchmark records contain a node outside the synthetic network family")
    demand_factors, profile_metadata = _simbench_hourly_factors(config.hours)
    outages = list(outage_rows(config, network_ids))
    requests, outcomes = _queue_and_outcomes(records, config, outages)
    validate_chronological_tables(outages, requests, outcomes)
    run_identity = {
        "schema_version": SCHEMA_VERSION,
        "start_at": config.start_at.isoformat(),
        "hours": config.hours,
        "requests_per_node": config.requests_per_node,
        "seed_version": config.seed_version,
        **profile_metadata,
        "record_fingerprint": hashlib.sha256(
            json.dumps([item.__dict__ for item in records], sort_keys=True).encode()
        ).hexdigest(),
    }
    run_id = hashlib.sha256(json.dumps(run_identity, sort_keys=True).encode()).hexdigest()[:16]
    destination = data_root / "simulations" / SCHEMA_VERSION / run_id
    (work_root / "staging").mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="synthetic-operator-", dir=work_root / "staging"))
    tables: dict[str, dict[str, Any]] = {}
    try:
        row_sources: dict[str, Iterable[dict[str, Any]]] = {
            "network_assets": network_asset_rows(network_ids),
            "hourly_operating_states": hourly_operating_rows(
                records, config, demand_factors, profile_metadata
            ),
            "outages": outages,
            "queue_requests": requests,
            "connection_study_outcomes": outcomes,
            "flexibility_contracts": flexibility_contract_rows(),
        }
        for name, rows in row_sources.items():
            staged = staging / f"{name}.jsonl.gz"
            count, digest, byte_length = _write_gzip_jsonl(staged, rows)
            target = destination / staged.name
            atomic_write(target, staged.read_bytes())
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise OSError(f"synthetic table verification failed: {name}")
            tables[name] = {
                "path": str(target.relative_to(data_root)),
                "rows": count,
                "sha256": digest,
                "bytes": byte_length,
            }
        manifest = {
            **run_identity,
            "run_id": run_id,
            "truth_class": TRUTH_CLASS,
            "capacity_claim": False,
            "operator_validated": False,
            "available_capacity_mw": None,
            "tables": tables,
            "quality": {
                "chronological_queue": True,
                "publication_revisions_preserved": True,
                "hourly_asset_loading_solved": False,
                "network_family_count": len({item.network_id for item in records}),
                "candidate_node_count": len({item.node_id for item in records}),
                "limitations": [
                    "Every electrical, outage, queue and outcome value is synthetic.",
                    "Hourly asset loading is null because no hourly branch-flow solve was run.",
                    "Synthetic decisions are workflow labels, not historical operator outcomes.",
                    "Public geographic anchors do not establish connection feasibility.",
                ],
            },
        }
        encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        atomic_write(destination / "manifest.json", encoded)
        return {**manifest, "manifest_path": str(destination / "manifest.json")}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def benchmark_records_from_report(path: Path) -> list[BenchmarkRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [BenchmarkRecord(**item) for item in payload.get("records", [])]


def iter_synthetic_table(
    data_root: Path, manifest: dict[str, Any], name: str
) -> Iterator[dict[str, Any]]:
    if name not in manifest.get("tables", {}):
        raise ValueError(f"synthetic package table is unavailable: {name}")
    path = (data_root / manifest["tables"][name]["path"]).resolve()
    try:
        path.relative_to(data_root.resolve())
    except ValueError as error:
        raise ValueError("synthetic package table escapes the data root") from error
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def read_synthetic_table(
    data_root: Path, manifest: dict[str, Any], name: str
) -> list[dict[str, Any]]:
    return list(iter_synthetic_table(data_root, manifest, name))


def verify_synthetic_operator_package(manifest_path: Path, data_root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported synthetic operator package")
    if manifest.get("truth_class") != TRUTH_CLASS or manifest.get("capacity_claim") is not False:
        raise ValueError("synthetic package truth boundary is invalid")
    if manifest.get("available_capacity_mw") is not None or manifest.get("operator_validated"):
        raise ValueError("synthetic package cannot contain operator-confirmed capacity")
    tables = manifest.get("tables", {})
    if set(tables) != REQUIRED_TABLES:
        raise ValueError("synthetic package table inventory is incomplete")
    checked_rows = 0
    for name, metadata in tables.items():
        path = (data_root / metadata["path"]).resolve()
        try:
            path.relative_to(data_root.resolve())
        except ValueError as error:
            raise ValueError(f"synthetic table escapes the data root: {name}") from error
        content = path.read_bytes()
        if len(content) != metadata["bytes"]:
            raise ValueError(f"synthetic table byte length mismatch: {name}")
        if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
            raise ValueError(f"synthetic table hash mismatch: {name}")
        with gzip.open(path, "rt", encoding="utf-8") as source:
            rows = sum(1 for line in source if line.strip())
        if rows != metadata["rows"]:
            raise ValueError(f"synthetic table row count mismatch: {name}")
        checked_rows += rows
    return {
        "status": "verified",
        "run_id": manifest["run_id"],
        "tables": len(tables),
        "rows": checked_rows,
        "capacity_claim": False,
    }
