"""Explicit readiness status for pilot datasets that cannot be fabricated in software."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DataReadinessState(str, Enum):
    AVAILABLE_AUTHORITATIVE = "available_authoritative"
    AVAILABLE_PUBLIC = "available_public"
    SYNTHETIC_SUBSTITUTE = "synthetic_substitute"
    REQUESTED = "requested"
    BLOCKING = "blocking"


@dataclass(frozen=True)
class DatasetReadiness:
    dataset_id: str
    state: DataReadinessState
    evidence_fingerprint: str | None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class PilotDataReadiness:
    datasets: tuple[DatasetReadiness, ...]
    shadow_pilot_ready: bool
    dependable_claim_ready: bool
    blockers: tuple[str, ...]


def assess_pilot_data_readiness(
    datasets: tuple[DatasetReadiness, ...], *, required_dataset_ids: tuple[str, ...]
) -> PilotDataReadiness:
    if not datasets or len({item.dataset_id for item in datasets}) != len(datasets):
        raise ValueError("pilot datasets must be non-empty and unique")
    by_id = {item.dataset_id: item for item in datasets}
    blockers = []
    for identifier in required_dataset_ids:
        item = by_id.get(identifier)
        if item is None:
            blockers.append(f"missing:{identifier}")
        elif item.state in {DataReadinessState.REQUESTED, DataReadinessState.BLOCKING}:
            blockers.append(f"unavailable:{identifier}")
    shadow_ready = not blockers
    authoritative = shadow_ready and all(
        by_id[item].state == DataReadinessState.AVAILABLE_AUTHORITATIVE
        for item in required_dataset_ids
    )
    return PilotDataReadiness(tuple(datasets), shadow_ready, authoritative, tuple(blockers))
