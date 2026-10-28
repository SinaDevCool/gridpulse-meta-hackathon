"""Provider-neutral electricity-price CSV parser."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from math import isfinite

from capacity_backtest.domain.base import parse_aware_timestamp


@dataclass(frozen=True)
class PriceObservation:
    timestamp: str
    price_eur_per_mwh: float
    market: str
    source_id: str


def parse_price_csv(content: bytes, *, source_id: str) -> tuple[PriceObservation, ...]:
    rows = []
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    if set(reader.fieldnames or ()) != {"timestamp", "price_eur_per_mwh", "market"}:
        raise ValueError("price CSV schema drift")
    for row in reader:
        parse_aware_timestamp(row["timestamp"], "price timestamp")
        price = float(row["price_eur_per_mwh"])
        if not isfinite(price) or not row["market"] or not source_id:
            raise ValueError("price observation is invalid")
        rows.append(PriceObservation(row["timestamp"], price, row["market"], source_id))
    instants = [parse_aware_timestamp(item.timestamp, "price timestamp") for item in rows]
    if not rows or instants != sorted(set(instants)):
        raise ValueError("price observations must be non-empty, unique and chronological")
    return tuple(rows)
