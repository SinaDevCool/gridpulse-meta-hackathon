"""Versioned, provider-neutral market-product contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from capacity_backtest.contracts import TruthClass, coerce_truth_class
from capacity_backtest.domain.base import parse_aware_timestamp
from capacity_backtest.domain.evidence import EvidenceReference


class MarketDirection(str, Enum):
    REDUCE_IMPORT = "reduce_import"
    INCREASE_IMPORT = "increase_import"
    SYMMETRIC = "symmetric"


class PaymentType(str, Enum):
    AVAILABILITY = "availability"
    UTILIZATION = "utilization"
    COMBINED = "combined"


@dataclass(frozen=True)
class MarketProduct:
    product_id: str
    market: str
    jurisdiction: str
    direction: MarketDirection
    minimum_bid_mw: float
    granularity_minutes: int
    notice_minutes: int
    response_seconds: int
    minimum_duration_minutes: int
    maximum_duration_minutes: int
    maximum_events_per_day: int
    availability_start_hour: int
    availability_end_hour: int
    baseline_method: str
    payment_type: PaymentType
    availability_payment_eur_per_mw_hour: float
    utilization_payment_eur_per_mwh: float
    non_delivery_penalty_eur_per_mwh: float
    effective_from: str
    effective_to: str
    truth_class: TruthClass
    evidence: tuple[EvidenceReference, ...] = ()
    schema_version: str = "gridpulse-market-product-v1"

    def validate(self) -> None:
        if self.schema_version != "gridpulse-market-product-v1" or not all(
            (self.product_id, self.market, self.jurisdiction, self.baseline_method)
        ):
            raise ValueError("market product identity is invalid")
        start = parse_aware_timestamp(self.effective_from, "effective_from")
        end = parse_aware_timestamp(self.effective_to, "effective_to")
        if start >= end:
            raise ValueError("market product effective period is invalid")
        numeric = (
            self.minimum_bid_mw, self.granularity_minutes, self.notice_minutes,
            self.response_seconds, self.minimum_duration_minutes,
            self.maximum_duration_minutes, self.maximum_events_per_day,
            self.availability_payment_eur_per_mw_hour,
            self.utilization_payment_eur_per_mwh,
            self.non_delivery_penalty_eur_per_mwh,
        )
        if min(numeric) < 0 or self.granularity_minutes <= 0:
            raise ValueError("market product limits cannot be negative")
        if self.minimum_duration_minutes > self.maximum_duration_minutes:
            raise ValueError("market product duration bounds are reversed")
        if not 0 <= self.availability_start_hour <= 23 or not 1 <= self.availability_end_hour <= 24:
            raise ValueError("market availability hours are invalid")
        coerce_truth_class(self.truth_class)
        for reference in self.evidence:
            reference.validate()
