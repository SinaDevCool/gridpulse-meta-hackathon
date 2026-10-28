"""Adapters into the existing, tested Pandapower network-study boundary."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from grid_data.network_study import NetworkModelInput

from .contracts import NetworkModelRealization


def validate_network_model(model: NetworkModelInput) -> None:
    bus_ids = {str(item["id"]) for item in model.buses}
    if model.connection_bus not in bus_ids:
        raise ValueError("connection bus is absent from network buses")
    if not model.provenance.get("source_url") or not model.provenance.get("license"):
        raise ValueError("network provenance requires source_url and license")
    asset_ids: set[str] = set()
    for collection in (model.branches, model.transformers):
        for asset in collection:
            asset_id = str(asset["id"])
            if asset_id in asset_ids:
                raise ValueError(f"duplicate electrical asset identity: {asset_id}")
            asset_ids.add(asset_id)
    for branch in model.branches:
        if str(branch["from_bus"]) not in bus_ids or str(branch["to_bus"]) not in bus_ids:
            raise ValueError(f"branch {branch['id']} references an unknown bus")
    for transformer in model.transformers:
        if str(transformer["hv_bus"]) not in bus_ids or str(transformer["lv_bus"]) not in bus_ids:
            raise ValueError(f"transformer {transformer['id']} references an unknown bus")


def realization_model(realization: NetworkModelRealization) -> NetworkModelInput:
    realization.validate()
    if not isinstance(realization.model, NetworkModelInput):
        raise TypeError("network realization model must be NetworkModelInput")
    model = copy.deepcopy(realization.model)
    model = NetworkModelInput(**{**model.__dict__, "connection_bus": realization.pcc.bus_id})
    validate_network_model(model)
    return model


def load_canonical_network_json(path: Path) -> NetworkModelInput:
    """Load a manifested public/operator network already normalized to the canonical schema."""

    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "buses",
        "branches",
        "transformers",
        "loads",
        "generators",
        "switches",
        "contingencies",
        "connection_bus",
        "study_year",
        "provenance",
    }
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"network JSON is missing fields: {sorted(missing)}")
    model = NetworkModelInput(
        **{key: payload[key] for key in NetworkModelInput.__dataclass_fields__ if key in payload}
    )
    validate_network_model(model)
    return model


def simbench_network(code: str, *, connection_bus: str | None = None) -> NetworkModelInput:
    """Convert a SimBench pandapower net into the existing explicit network contract."""

    try:
        import simbench as sb  # type: ignore[import-untyped]
    except ImportError as error:
        raise RuntimeError("simbench study dependency is not installed") from error
    net = sb.get_simbench_net(code)
    buses = [
        {
            "id": f"bus-{index}",
            "name": str(row.get("name", index)),
            "vn_kv": float(row.vn_kv),
            **(
                {"latitude": float(row.geo[1]), "longitude": float(row.geo[0])}
                if isinstance(row.get("geo"), (list, tuple)) and len(row.geo) >= 2
                else {}
            ),
        }
        for index, row in net.bus.iterrows()
    ]
    branches = [
        {
            "id": f"line-{index}",
            "from_bus": f"bus-{int(row.from_bus)}",
            "to_bus": f"bus-{int(row.to_bus)}",
            "length_km": float(row.length_km),
            "r_ohm_per_km": float(row.r_ohm_per_km),
            "x_ohm_per_km": float(row.x_ohm_per_km),
            "c_nf_per_km": float(row.c_nf_per_km),
            "max_i_ka": float(row.max_i_ka),
        }
        for index, row in net.line.iterrows()
        if bool(row.get("in_service", True))
    ]
    transformers = [
        {
            "id": f"trafo-{index}",
            "hv_bus": f"bus-{int(row.hv_bus)}",
            "lv_bus": f"bus-{int(row.lv_bus)}",
            "sn_mva": float(row.sn_mva),
            "vn_hv_kv": float(row.vn_hv_kv),
            "vn_lv_kv": float(row.vn_lv_kv),
            "vk_percent": float(row.vk_percent),
            "vkr_percent": float(row.vkr_percent),
            "pfe_kw": float(row.pfe_kw),
            "i0_percent": float(row.i0_percent),
        }
        for index, row in net.trafo.iterrows()
        if bool(row.get("in_service", True))
    ]
    loads = [
        {
            "id": f"load-{index}",
            "bus": f"bus-{int(row.bus)}",
            "p_mw": float(row.p_mw),
            "q_mvar": float(row.q_mvar),
        }
        for index, row in net.load.iterrows()
        if bool(row.get("in_service", True))
    ]
    active_line_ids = {item["id"] for item in branches}
    active_transformer_ids = {item["id"] for item in transformers}
    switches = []
    for index, row in net.switch.iterrows():
        element_type = str(row.et)
        if element_type == "l":
            element_id = f"line-{int(row.element)}"
            if element_id not in active_line_ids:
                continue
            canonical_type = "line"
        elif element_type == "t":
            element_id = f"trafo-{int(row.element)}"
            if element_id not in active_transformer_ids:
                continue
            canonical_type = "transformer"
        elif element_type == "b":
            element_id = f"bus-{int(row.element)}"
            canonical_type = "bus"
        else:
            continue
        switches.append(
            {
                "id": f"switch-{index}",
                "bus": f"bus-{int(row.bus)}",
                "element_id": element_id,
                "element_type": canonical_type,
                "closed": bool(row.closed),
            }
        )
    slack_bus = f"bus-{int(net.ext_grid.iloc[0].bus)}"
    generators: list[dict[str, Any]] = [
        {"id": "simbench-slack", "bus": slack_bus, "kind": "external_grid"}
    ]
    generators.extend(
        {
            "id": f"simbench-sgen-{index}",
            "bus": f"bus-{int(row.bus)}",
            "kind": "static_generator",
            "p_mw": float(row.p_mw),
            "q_mvar": float(row.q_mvar),
        }
        for index, row in net.sgen.iterrows()
        if bool(row.get("in_service", True))
    )
    generators.extend(
        {
            "id": f"simbench-gen-{index}",
            "bus": f"bus-{int(row.bus)}",
            "kind": "generator",
            "p_mw": float(row.p_mw),
            "q_mvar": float(row.get("q_mvar", 0.0)),
        }
        for index, row in net.gen.iterrows()
        if bool(row.get("in_service", True))
    )
    selected_bus = str(
        connection_bus or next((item["id"] for item in buses if item["id"] != slack_bus), slack_bus)
    )
    model = NetworkModelInput(
        buses,
        branches,
        transformers,
        loads,
        generators,
        switches,
        [],
        selected_bus,
        2026,
        {
            "source_url": "https://simbench.de/",
            "license": "SimBench dataset license",
            "simbench_code": code,
        },
        model_id=f"simbench-{code}",
        model_version="simbench-package",
        validation_class="synthetic_demonstration",
    )
    validate_network_model(model)
    return model
