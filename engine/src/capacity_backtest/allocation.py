"""Berlin allocation evidence without residual-capacity inference."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .contracts import TruthClass


@dataclass(frozen=True)
class AllocationRound:
    year: int
    requested_mva: float | None
    request_count: int | None
    eligible_request_count: int | None
    allocated_request_count: int | None
    allocated_mva: float | None
    technical_area_count: int | None
    source_id: str
    truth_class: TruthClass = TruthClass.OPERATOR_PUBLISHED
    remaining_mva: None = None

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["truth_class"] = self.truth_class.value
        return value


def parse_berlin_2025_allocation(text: str) -> AllocationRound:
    normalized = " ".join(text.split()).replace(".", "")

    def number(pattern: str) -> float | None:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        return float(match.group(1).replace(",", ".")) if match else None

    return AllocationRound(
        year=2025,
        requested_mva=number(r"(?:rund|around)\s+([0-9]+(?:,[0-9]+)?)\s*MVA"),
        request_count=int(number(r"([0-9]+)\s+(?:Anfragen|requests)") or 0) or None,
        eligible_request_count=int(
            number(r"([0-9]+)\s+Anfragen\s+(?:vollständig|vollstaendig|complete)") or 0
        )
        or None,
        allocated_request_count=int(
            number(r"([0-9]+)\s+(?:Antragstellern|requests?)\s+(?:konnten|were)") or 0
        )
        or None,
        allocated_mva=number(r"([0-9]+(?:,[0-9]+)?)\s*MVA\s+(?:vergeben|allocated)"),
        technical_area_count=int(number(r"(?:drei|three)\s+Netzgebieten") or 3),
        source_id="stromnetz_berlin_allocation_2025",
    )


def allocation_ratio(round_: AllocationRound) -> float | None:
    if not round_.requested_mva or round_.allocated_mva is None:
        return None
    return round_.allocated_mva / round_.requested_mva
