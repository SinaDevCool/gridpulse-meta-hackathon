"""Canonical multi-PCC capacity-study application service and persistence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain import CapacityEnvelopeResult, RunProvenance
from capacity_backtest.domain.flexibility_requirement import FlexibilityRequirement
from capacity_backtest.domain.results import CAPACITY_RESULT_SCHEMA_VERSION
from capacity_backtest.phase1.ac_envelope import OperatingState, run_ac_envelope_study
from capacity_backtest.pipeline import CapacityStudyPipelineStages, StudyPipeline
from capacity_backtest.storage import StorageLayout, atomic_write, initialise_storage
from grid_data.berlin_synthetic_capacity import build_berlin_synthetic_model
from grid_data.network_study import PandapowerProvider

from .aggregation import RealizationEnvelope, aggregate_capacity
from .blockers import capacity_blockers
from .contingencies import apply_known_outages, exhaustive_n_minus_one
from .contracts import CandidatePCC, CapacityBlocker, CapacityStatistics, PCCStatus
from .ensemble import build_network_ensemble
from .flexibility_requirement import OperatingTerms, build_flexibility_requirement
from .network_adapter import load_canonical_network_json, realization_model, simbench_network
from .operating_states import assemble_operating_states, mock_operator_series
from .pcc import generate_pcc_hypotheses

RUN_SCHEMA_VERSION = "gridpulse-capacity-study-run-v2"
MANIFEST_SCHEMA_VERSION = "gridpulse-capacity-run-manifest-v2"


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(_json_value(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PCCStudyResult:
    pcc: CandidatePCC
    statistics: CapacityStatistics
    capacity_result: CapacityEnvelopeResult
    flexibility_requirement: FlexibilityRequirement
    blockers: tuple[CapacityBlocker, ...]
    realization_count: int
    successful_realization_count: int

    def validate(self) -> None:
        self.pcc.validate()
        self.statistics.validate()
        self.capacity_result.validate()
        self.flexibility_requirement.validate()
        if self.flexibility_requirement.pcc_id != self.pcc.pcc_id:
            raise ValueError("flexibility requirement and PCC identities do not match")
        if self.flexibility_requirement.capacity_result_id != self.capacity_result.result_id:
            raise ValueError("flexibility requirement references a different capacity result")
        if self.flexibility_requirement.capacity_provenance_fingerprint != self.capacity_result.provenance.fingerprint():
            raise ValueError("flexibility requirement provenance does not match capacity result")
        if not 0 <= self.successful_realization_count <= self.realization_count:
            raise ValueError("invalid successful realization count")
        for blocker in self.blockers:
            blocker.validate()

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return _json_value(asdict(self))


@dataclass(frozen=True)
class CapacityStudyRun:
    run_id: str
    input_fingerprint: str
    configuration: dict[str, Any]
    pcc_results: tuple[PCCStudyResult, ...]
    truth_class: str
    report_subject_pcc_id: str
    operator_selected_pcc_id: str | None = None
    capacity_claim: bool = False
    schema_version: str = RUN_SCHEMA_VERSION

    @property
    def pccs(self) -> tuple[CandidatePCC, ...]:
        return tuple(item.pcc for item in self.pcc_results)

    @property
    def statistics(self) -> CapacityStatistics:
        return self.result_for_pcc(self.report_subject_pcc_id).statistics

    @property
    def realization_count(self) -> int:
        return sum(item.realization_count for item in self.pcc_results)

    @property
    def successful_realization_count(self) -> int:
        return sum(item.successful_realization_count for item in self.pcc_results)

    @property
    def blockers(self) -> dict[str, tuple[CapacityBlocker, ...]]:
        return {item.pcc.pcc_id: item.blockers for item in self.pcc_results}

    def result_for_pcc(self, pcc_id: str) -> PCCStudyResult:
        result = next((item for item in self.pcc_results if item.pcc.pcc_id == pcc_id), None)
        if result is None:
            raise ValueError(f"unknown PCC result: {pcc_id}")
        return result

    def validate(self) -> None:
        if self.schema_version != RUN_SCHEMA_VERSION or not self.run_id:
            raise ValueError("unsupported or unidentified capacity-study run")
        if len(self.input_fingerprint) != 64 or not self.pcc_results:
            raise ValueError("capacity study requires a fingerprint and PCC results")
        identifiers = [item.pcc.pcc_id for item in self.pcc_results]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("capacity-study PCC results must be unique")
        for item in self.pcc_results:
            item.validate()
        if self.report_subject_pcc_id not in identifiers:
            raise ValueError("report subject must reference a study PCC")
        if self.operator_selected_pcc_id is not None:
            selected = self.result_for_pcc(self.operator_selected_pcc_id)
            if selected.pcc.status != PCCStatus.OPERATOR_CONFIRMED:
                raise ValueError("only an operator-confirmed PCC can be operator-selected")
        if coerce_truth_class(self.truth_class) != TruthClass.OPERATOR_CONFIRMED and self.capacity_claim:
            raise ValueError("non-operator study cannot make a capacity claim")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return _json_value(asdict(self))


def _load_configuration(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("capacity study configuration must be a mapping")
    return payload


def _network(config: dict[str, Any], root: Path):
    network = config.get("network", {})
    mode = network.get("mode", "mock_berlin")
    if mode == "mock_berlin":
        return build_berlin_synthetic_model()
    if mode == "canonical_json":
        path = Path(network["path"])
        return load_canonical_network_json(path if path.is_absolute() else root / path)
    if mode == "simbench":
        return simbench_network(str(network["code"]), connection_bus=network.get("connection_bus"))
    raise ValueError(f"unsupported network mode: {mode}")


def _states(config: dict[str, Any]):
    state = config.get("operating_states", {})
    start = datetime.fromisoformat(str(state.get("start", "2026-01-01T00:00:00+00:00")))
    if start.tzinfo is None:
        raise ValueError("operating-state start must be timezone-aware")
    timestamps = [(start + timedelta(hours=i)).isoformat() for i in range(int(state.get("hours", 24)))]
    cutoff = str(config.get("evidence_cutoff", datetime.now(timezone.utc).isoformat()))
    if state.get("mode", "mock_operator") == "mock_operator":
        return mock_operator_series(timestamps=timestamps, evidence_cutoff=cutoff, seed=int(state.get("seed", 42)), peak_load_mw=float(state.get("peak_load_mw", 200)), generation_capacity_mw=float(state.get("generation_capacity_mw", 80)))
    return assemble_operating_states(series_id=str(state.get("series_id", "configured-operating-states")), timestamps=timestamps, regional_load_mw=[float(x) for x in state["regional_load_mw"]], regional_generation_mw=[float(x) for x in state["regional_generation_mw"]], nodal_load_fraction=float(state["nodal_load_fraction"]), nodal_generation_fraction=float(state["nodal_generation_fraction"]), committed_connections_mw=state.get("committed_connections_mw"), reservations_mw=state.get("reservations_mw"), evidence_cutoff=cutoff, active_outage_ids=state.get("active_outage_ids"))


def _candidate_pccs(config: dict[str, Any], model: Any) -> tuple[CandidatePCC, ...]:
    site = config["site"]
    if config.get("pcc_hypotheses"):
        result = tuple(CandidatePCC(str(x["pcc_id"]), str(x["bus_id"]), str(x["operator_id"]), float(x["voltage_kv"]), x.get("latitude"), x.get("longitude"), x.get("distance_km"), PCCStatus(str(x.get("status", "reconstructed"))), float(x.get("confidence", 0.5)), TruthClass.EXPERIMENTAL_ESTIMATE) for x in config["pcc_hypotheses"])
    else:
        result = generate_pcc_hypotheses(site_latitude=float(site["latitude"]), site_longitude=float(site["longitude"]), requested_capacity_mw=float(site["requested_capacity_mw"]), operator_id=str(site["operator_id"]), buses=model.buses, maximum_candidates=int(config.get("maximum_pcc_candidates", 3)), minimum_voltage_kv=config.get("minimum_voltage_kv"))
    for pcc in result:
        pcc.validate()
    return result


def _truth(config: dict[str, Any]) -> TruthClass:
    return TruthClass.SYNTHETIC_DEMONSTRATION if config.get("network", {}).get("mode", "mock_berlin") == "mock_berlin" else TruthClass.EXPERIMENTAL_ESTIMATE


def _terms(config: dict[str, Any]) -> OperatingTerms:
    values = config.get("planning", {}).get("operating_terms", {})
    return OperatingTerms(**{name: values.get(name) for name in OperatingTerms.__dataclass_fields__})


def _conditional(stats: CapacityStatistics, config: dict[str, Any]) -> tuple[float, float | None, tuple[str, ...]]:
    policy = config.get("planning", {}).get("conditional_capacity")
    if not policy:
        return stats.firm_capacity_mw, None, ("conditional_capacity_policy_unknown",)
    if policy.get("method") != "availability_level":
        raise ValueError("unsupported conditional-capacity policy")
    level = float(policy["availability"])
    match = next((x for x in stats.availability_capacities if abs(x.availability - level) < 1e-9), None)
    if match is None:
        raise ValueError("conditional availability level was not calculated")
    return max(stats.firm_capacity_mw, match.capacity_mw), level, ()


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _build_pipeline_stages(config: dict[str, Any], layout: StorageLayout) -> CapacityStudyPipelineStages:
    runtime: dict[str, Any] = {}
    config_hash = _canonical_hash(config)

    def prepare() -> dict[str, Any]:
        cutoff = str(config.get("evidence_cutoff", ""))
        if not cutoff:
            raise ValueError("capacity study requires an explicit evidence_cutoff")
        cutoff_time = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        decision = str(config.get("decision_time", cutoff))
        decision_time = datetime.fromisoformat(decision.replace("Z", "+00:00"))
        if cutoff_time.tzinfo is None or decision_time.tzinfo is None or decision_time < cutoff_time:
            raise ValueError("decision_time and evidence_cutoff must be aligned aware timestamps")
        runtime["decision_time"] = decision
        return {"evidence_validated": True, "evidence_cutoff": cutoff, "decision_time": decision, "configuration_sha256": config_hash}

    def screen(prepared: dict[str, Any]) -> dict[str, Any]:
        model = _network(config, layout.project_root)
        pccs = _candidate_pccs(config, model)
        states = _states(config)
        options = config.get("ensemble", {})
        realizations = build_network_ensemble(model, pccs, samples_per_pcc=int(options.get("samples_per_pcc", 2)), seed=int(options.get("seed", 2026)), load_scale_bounds=tuple(options.get("load_scale_bounds", (0.9, 1.1))), branch_rating_scale_bounds=tuple(options.get("branch_rating_scale_bounds", (0.85, 1.05))), transformer_rating_scale_bounds=tuple(options.get("transformer_rating_scale_bounds", (0.85, 1.05))), truth_class=_truth(config))
        hashes = {"configuration": prepared["configuration_sha256"], "network": _canonical_hash(asdict(model)), "operating_states": _canonical_hash(asdict(states)), "pcc_hypotheses": _canonical_hash([asdict(x) for x in pccs]), "ensemble": _canonical_hash(options)}
        fingerprint = _canonical_hash(hashes)
        runtime.update(model=model, pccs=pccs, states=states, realizations=realizations, hashes=hashes, fingerprint=fingerprint)
        return {"requires_detailed_verification": True, "network_model_id": model.model_id, "pcc_ids": [x.pcc_id for x in pccs], "realization_ids": [x.realization_id for x in realizations], "input_hashes": hashes, "input_fingerprint": fingerprint}

    def verify(_prepared: dict[str, Any], _screening: dict[str, Any]) -> dict[str, Any]:
        provider = PandapowerProvider(capacity_tolerance_mw=float(config.get("capacity_tolerance_mw", 0.5)), maximum_capacity_mw=float(config.get("maximum_capacity_mw", 500)), incremental_load_power_factor=float(config.get("incremental_load_power_factor", 0.97)))
        rows: list[RealizationEnvelope] = []
        for realization in runtime["realizations"]:
            try:
                model = realization_model(realization)
                values: list[float] = []
                constraints: list[str] = []
                lower = False
                for point in runtime["states"].points:
                    operating_model = apply_known_outages(model, point.active_outage_ids) if point.active_outage_ids else exhaustive_n_minus_one(model)
                    operating = OperatingState(point.timestamp, point.background_load_mw + point.committed_connections_mw, point.background_generation_mw, point.reactive_power_mvar, point.reservations_mw)
                    study = run_ac_envelope_study(operating_model, [operating], provider, power_factor=float(config.get("incremental_load_power_factor", 0.97)), truth_class=realization.truth_class, envelope_id=f"envelope-{realization.realization_id}-{point.timestamp}")
                    values.append(study.envelope.n1_import_mw[0])
                    constraints.append(str(study.envelope.binding_constraints[0] or "unknown"))
                    lower = lower or study.states[0].capacity_is_lower_bound
                rows.append(RealizationEnvelope(realization.realization_id, realization.probability_weight, tuple(values), tuple(constraints), True, lower, realization.pcc.pcc_id))
            except (RuntimeError, ValueError) as error:
                rows.append(RealizationEnvelope(realization.realization_id, realization.probability_weight, (), (f"{type(error).__name__}: {error}",), False, False, realization.pcc.pcc_id))
        runtime["envelopes"] = rows
        by_pcc = {pcc.pcc_id: any(x.succeeded and x.secure_capacity_mw for x in rows if x.pcc_id == pcc.pcc_id) for pcc in runtime["pccs"]}
        return {"physics_verified": all(by_pcc.values()), "verified_by_pcc": by_pcc, "realizations": [{"pcc_id": x.pcc_id, "realization_id": x.realization_id, "succeeded": x.succeeded and bool(x.secure_capacity_mw), "capacity_is_lower_bound": x.capacity_is_lower_bound, "failure_reason": None if x.succeeded else x.binding_constraints[0]} for x in rows]}

    def aggregate(_prepared: dict[str, Any], _screening: dict[str, Any], _verification: dict[str, Any]) -> dict[str, Any]:
        by_pcc = {}
        for pcc in runtime["pccs"]:
            rows = [x for x in runtime["envelopes"] if x.pcc_id == pcc.pcc_id]
            by_pcc[pcc.pcc_id] = aggregate_capacity(rows, requested_capacity_mw=float(config["site"]["requested_capacity_mw"]), interval_hours=runtime["states"].interval_hours)
        runtime["statistics"] = by_pcc
        return {"pcc_isolation_verified": True, "statistics_by_pcc": {key: value.as_dict() for key, value in by_pcc.items()}}

    def build(prepared: dict[str, Any], _screening: dict[str, Any], _verification: dict[str, Any], _aggregation: dict[str, Any]) -> CapacityStudyRun:
        flags, site, results = config.get("operator_data", {}), config["site"], []
        for pcc in runtime["pccs"]:
            stats = runtime["statistics"][pcc.pcc_id]
            conditional, confidence, policy_blockers = _conditional(stats, config)
            blockers = capacity_blockers(pcc, operator_topology=bool(flags.get("topology")), operator_ratings=bool(flags.get("ratings")), operator_loading=bool(flags.get("loading")), operator_queue=bool(flags.get("queue")), operator_contingencies=bool(flags.get("contingencies")))
            provenance = RunProvenance(run_id=f"{runtime['fingerprint'][:20]}-{pcc.pcc_id}", created_at=runtime["decision_time"], evidence_cutoff=prepared["evidence_cutoff"], code_version=str(config.get("code_version", "working-tree")), assumption_set_id=str(config.get("assumption_set_id", "capacity-study-config-v1")), solver_name="pandapower", solver_version=_pkg_version("pandapower"), input_hashes={**runtime["hashes"], "pcc": _canonical_hash(asdict(pcc))}, evidence=tuple(pcc.evidence), metadata={"pcc_id": pcc.pcc_id, "network_model_id": runtime["model"].model_id})
            identity = _canonical_hash({"input_fingerprint": runtime["fingerprint"], "pcc_id": pcc.pcc_id, "capacity_schema": CAPACITY_RESULT_SCHEMA_VERSION, "conditional_policy": config.get("planning", {}).get("conditional_capacity")})
            binding = max(stats.binding_constraint_counts, key=stats.binding_constraint_counts.get, default="unknown")
            capacity = CapacityEnvelopeResult(f"capacity-{identity[:20]}", f"{site['site_id']}:{pcc.pcc_id}", _truth(config), stats.firm_capacity_mw, conditional, min(float(site["requested_capacity_mw"]), conditional), confidence, binding, tuple([x.code for x in blockers] + list(policy_blockers) + ["protection_harmonics_short_circuit_and_dynamics_unverified"]), False, provenance, None)
            requirement = build_flexibility_requirement(capacity, site_id=str(site["site_id"]), pcc_id=pcc.pcc_id, requested_import_mw=float(site["requested_capacity_mw"]), expected_provenance_fingerprint=provenance.fingerprint(), operating_terms=_terms(config), assumption_ids=tuple(str(x) for x in config.get("assumption_ids", ())), capacity_is_lower_bound=stats.lower_bound_realization_fraction > 0)
            rows = [x for x in runtime["envelopes"] if x.pcc_id == pcc.pcc_id]
            results.append(PCCStudyResult(pcc, stats, capacity, requirement, blockers, len(rows), sum(x.succeeded and bool(x.secure_capacity_mw) for x in rows)))
        run = CapacityStudyRun(runtime["fingerprint"][:20], runtime["fingerprint"], config, tuple(results), _truth(config).value, results[0].pcc.pcc_id)
        run.validate()
        return run

    return CapacityStudyPipelineStages(prepare, screen, verify, aggregate, build)


def run_capacity_study(config_path: Path, layout: StorageLayout) -> tuple[CapacityStudyRun, Path]:
    initialise_storage(layout, require_cloud=True)
    pipeline_run = StudyPipeline.run_capacity_study(_build_pipeline_stages(_load_configuration(config_path), layout))
    run: CapacityStudyRun = pipeline_run.result
    destination = layout.data_root / "runs" / RUN_SCHEMA_VERSION / run.run_id
    payload = json.dumps(run.as_dict(), indent=2, ensure_ascii=False) + "\n"
    report = render_capacity_report(run)
    atomic_write(destination / "capacity-study.json", payload.encode())
    atomic_write(destination / "capacity-study.md", report.encode())
    manifest = {"schema_version": MANIFEST_SCHEMA_VERSION, "run_id": run.run_id, "input_fingerprint": run.input_fingerprint, "pipeline_fingerprint": pipeline_run.fingerprint(), "configuration_sha256": pipeline_run.prepared["configuration_sha256"], "artifact_sha256": {"capacity-study.json": hashlib.sha256(payload.encode()).hexdigest(), "capacity-study.md": hashlib.sha256(report.encode()).hexdigest()}, "capacity_result_sha256": {x.pcc.pcc_id: _canonical_hash(x.capacity_result.as_dict()) for x in run.pcc_results}, "flexibility_requirement_sha256": {x.pcc.pcc_id: _canonical_hash(x.flexibility_requirement.as_dict()) for x in run.pcc_results}, "truth_class": run.truth_class, "capacity_claim": False, "automatic_live_dispatch_authorized": False, "storage_path": str((destination / "capacity-study.json").relative_to(layout.data_root))}
    atomic_write(destination / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return run, destination


def render_capacity_report(run: CapacityStudyRun) -> str:
    sections = []
    for item in run.pcc_results:
        stats, req = item.statistics, item.flexibility_requirement
        availability = "\n".join(f"- {x.availability:.1%} availability: {x.capacity_mw:.3f} MW" for x in stats.availability_capacities)
        blockers = "\n".join(f"- `{x}`" for x in req.blockers) or "- None"
        response = "Unknown" if req.response_time_seconds is None else f"{req.response_time_seconds} seconds"
        duration = "Unknown" if req.maximum_event_duration_minutes is None else f"{req.maximum_event_duration_minutes} minutes"
        qualifier = ">= " if req.capacity_is_lower_bound else ""
        sections.append(f"## PCC {item.pcc.pcc_id}\n\n- PCC status: **{item.pcc.status.value}**\n- Firm screening capacity: **{qualifier}{stats.firm_capacity_mw:.3f} MW**\n- Conditional screening capacity: **{req.conditional_limit_mw:.3f} MW**\n- Requested import: **{req.requested_import_mw:.3f} MW**\n- Required reduction: **{req.required_reduction_mw:.3f} MW**\n- Feasible within conditional envelope: **{'Yes' if req.feasible_within_conditional_envelope else 'No'}**\n- Response time: **{response}**\n- Maximum event duration: **{duration}**\n- Truth class: **{req.truth_class.value}**\n- Operator-confirmed: **{'Yes' if req.operator_confirmed else 'No'}**\n\n### Availability curve\n\n{availability}\n\n### Flexibility blockers\n\n{blockers}\n")
    return "# GridPulse available-capacity and flexibility screening\n\n" + f"- Run ID: `{run.run_id}`\n- Input fingerprint: `{run.input_fingerprint}`\n- Operator-confirmed capacity claim: **No**\n- Automatic live dispatch authorized: **No**\n\n" + "\n".join(sections) + "\n## Boundary\n\nThis is a public/reconstructed or explicitly synthetic screening and simulation result. It is not an operator-confirmed connection offer. Candidate PCC, topology, ratings, loading, queue, protection, fault level, harmonics, operating terms and contingency policy require operator validation where listed as blockers in the JSON result.\n"
