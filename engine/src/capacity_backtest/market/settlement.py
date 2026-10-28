"""Market settlement over externally verified delivery quantities."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import MarketProduct


@dataclass(frozen=True)
class MarketSettlement:
    product_id: str
    availability_revenue_eur: float
    utilization_revenue_eur: float
    non_delivery_penalty_eur: float
    net_revenue_eur: float
    delivered_mwh: float
    shortfall_mwh: float
    schema_version: str = "gridpulse-market-settlement-v1"


def settle_delivery(
    product: MarketProduct,
    *,
    offered_mw: float,
    availability_hours: float,
    requested_mwh: float,
    verified_delivered_mwh: float,
) -> MarketSettlement:
    product.validate()
    if min(offered_mw, availability_hours, requested_mwh, verified_delivered_mwh) < 0:
        raise ValueError("settlement quantities cannot be negative")
    delivered = min(requested_mwh, verified_delivered_mwh)
    shortfall = max(0.0, requested_mwh - delivered)
    availability = offered_mw * availability_hours * product.availability_payment_eur_per_mw_hour
    utilization = delivered * product.utilization_payment_eur_per_mwh
    penalty = shortfall * product.non_delivery_penalty_eur_per_mwh
    return MarketSettlement(
        product.product_id, availability, utilization, penalty,
        availability + utilization - penalty, delivered, shortfall,
    )
