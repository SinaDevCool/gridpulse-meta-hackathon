"""Authenticated ENTSO-E capture and conservative time-series normalization."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from xml.etree import ElementTree

import httpx

from .storage import SnapshotStore

GERMANY_LUXEMBOURG_DOMAIN = "10Y1001A1001A82H"
API_URL = "https://web-api.tp.entsoe.eu/api"


@dataclass(frozen=True)
class EntsoeSeries:
    document_type: str
    points: dict[datetime, float]
    unit: str
    series_id: str | None = None
    business_type: str | None = None
    object_aggregation: str | None = None
    production_type: str | None = None
    resolution: str | None = None
    direction: str | None = None


def _text(element: ElementTree.Element, suffix: str) -> str | None:
    child = next((item for item in element.iter() if item.tag.endswith(suffix)), None)
    return child.text if child is not None else None


def parse_timeseries(xml: bytes, document_type: str) -> list[EntsoeSeries]:
    root = ElementTree.fromstring(xml)
    series: list[EntsoeSeries] = []
    for item in (node for node in root.iter() if node.tag.endswith("TimeSeries")):
        points: dict[datetime, float] = {}
        unit = _text(item, "quantity_Measure_Unit.name") or "unknown"
        is_price = document_type == "A44"
        if is_price:
            if _text(item, "currency_Unit.name") != "EUR" or _text(item, "price_Measure_Unit.name") != "MWH":
                raise ValueError("price series must explicitly use EUR/MWh")
            unit = "EUR/MWh"
        resolutions: set[str] = set()
        for period in (node for node in item.iter() if node.tag.endswith("Period")):
            start_text = _text(period, "start")
            resolution = _text(period, "resolution")
            if not start_text or resolution not in {"PT15M", "PT30M", "PT60M"}:
                continue
            resolutions.add(resolution)
            start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
            minutes = {"PT15M": 15, "PT30M": 30, "PT60M": 60}[resolution]
            for point in (node for node in period if node.tag.endswith("Point")):
                position = _text(point, "position")
                quantity = _text(point, "price.amount" if is_price else "quantity")
                if position and quantity:
                    timestamp = start + timedelta(minutes=minutes * (int(position) - 1))
                    value = float(quantity)
                    if is_price and (not isfinite(value) or int(position) < 1 or timestamp in points or start.tzinfo is None):
                        raise ValueError("price points require finite values and unique aware timestamps")
                    points[timestamp] = value
        if points:
            series.append(
                EntsoeSeries(
                    document_type=document_type,
                    points=points,
                    unit=unit,
                    series_id=_text(item, "mRID"),
                    business_type=_text(item, "businessType"),
                    object_aggregation=_text(item, "objectAggregation"),
                    production_type=_text(item, "psrType"),
                    resolution=next(iter(resolutions)) if len(resolutions) == 1 else None,
                    direction=(
                        "consumption"
                        if _text(item, "outBiddingZone_Domain.mRID")
                        else "generation"
                        if _text(item, "inBiddingZone_Domain.mRID")
                        else None
                    ),
                )
            )
    return series


def fetch_document(
    document_type: str,
    start: datetime,
    end: datetime,
    data_root: Path,
    *,
    client: httpx.Client | None = None,
    retries: int = 1,
) -> Path:
    token = os.environ.get("ENTSOE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("ENTSOE_TOKEN is not configured")
    params = {
        "securityToken": token,
        "documentType": document_type,
        "processType": "A16",
        "periodStart": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
        "periodEnd": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
    }
    domain_key = "outBiddingZone_Domain" if document_type == "A65" else "in_Domain"
    params[domain_key] = GERMANY_LUXEMBOURG_DOMAIN
    own_client = client is None
    http = client or httpx.Client(timeout=90, follow_redirects=True)
    try:
        response = None
        for attempt in range(retries + 1):
            try:
                response = http.get(API_URL, params=params)
                break
            except httpx.TransportError:
                if attempt >= retries:
                    raise
                time.sleep(1)
        assert response is not None
        response.raise_for_status()
        if b"Acknowledgement_MarketDocument" in response.content:
            reason = _text(ElementTree.fromstring(response.content), "text") or "request rejected"
            raise RuntimeError(f"ENTSO-E rejected request: {reason}")
        stored = SnapshotStore(data_root).capture(
            source_id=f"entsoe-timeseries-{document_type.lower()}",
            publisher="ENTSO-E Transparency Platform",
            source_url=API_URL,
            content=response.content,
            extension="xml",
            retrieved_at=datetime.now(timezone.utc),
            request={key: value for key, value in params.items() if key != "securityToken"},
            response_headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() in {"content-type", "content-length", "etag", "last-modified"}
            },
            truth_class="operator_published",
            geographic_resolution="germany_luxembourg_bidding_zone",
            adapter_version="entsoe-timeseries-v2",
            limitations=(
                "Germany-Luxembourg bidding-zone context; not a city or substation measurement.",
                "Does not establish available connection capacity, feasibility, cost or delivery timing.",
            ),
        )
        return stored.blob_path
    finally:
        if own_client:
            http.close()


def aggregate_hourly(series: list[EntsoeSeries]) -> dict[datetime, float]:
    """Average sub-hourly points per series, then sum distinct accepted series."""
    by_series: list[dict[datetime, list[float]]] = []
    for item in series:
        buckets: dict[datetime, list[float]] = {}
        for timestamp, value in item.points.items():
            hour = timestamp.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(hour, []).append(value)
        by_series.append(buckets)
    hours = sorted({hour for buckets in by_series for hour in buckets})
    return {
        hour: sum(
            sum(buckets[hour]) / len(buckets[hour]) for buckets in by_series if hour in buckets
        )
        for hour in hours
    }


def aggregate_generation_hourly(
    series: list[EntsoeSeries],
) -> dict[datetime, dict[str, float]]:
    """Return hourly production by PSR type and direction without mixing categories."""
    result: dict[datetime, dict[str, float]] = {}
    for item in series:
        if not item.production_type or not item.direction:
            raise ValueError("generation series requires production type and direction")
        hourly = aggregate_hourly([item])
        key = f"{item.production_type}_{item.direction}"
        for timestamp, value in hourly.items():
            bucket = result.setdefault(timestamp, {})
            if key in bucket:
                raise ValueError(f"duplicate generation identity at {timestamp}: {key}")
            bucket[key] = value
    return result
