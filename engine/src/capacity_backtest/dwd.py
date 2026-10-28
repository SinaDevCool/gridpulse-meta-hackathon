"""Immutable DWD hourly weather capture and source-aware normalization."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .storage import SnapshotStore, captured_blobs

BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly"
DATASETS = {
    "temperature": ("air_temperature/historical", "TU", ("TT_TU",)),
    "wind": ("wind/historical", "FF", ("F",)),
    "solar": ("solar", "ST", ("FG_LBERG", "FD_LBERG", "ZENIT")),
}
REGION_CENTRES = {
    "DE-BE": (52.5200, 13.4050),
    "DE-BB": (52.4125, 12.5316),
    "DE-HB": (53.0793, 8.8017),
    "DE-HE-FRA": (50.1109, 8.6821),
    "DE-RHEIN-MAIN": (50.0700, 8.3500),
}


@dataclass(frozen=True)
class WeatherProfile:
    region_id: str
    variable: str
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    rows: int
    first_timestamp: str
    last_timestamp: str
    duplicate_timestamps: int
    missing_hours: int
    rejected_values: int
    accepted: bool
    reasons: tuple[str, ...]


def _stations(text: str) -> list[dict[str, object]]:
    rows = []
    for line in text.splitlines()[2:]:
        match = re.match(
            r"\s*(\d+)\s+(\d{8})\s+(\d{8})\s+(-?\d+)\s+([\d.-]+)\s+([\d.-]+)\s+(.{1,41})\s+(.+?)\s+(?:Frei|$)",
            line,
        )
        if match:
            rows.append(
                {
                    "id": match.group(1).zfill(5),
                    "start": match.group(2),
                    "end": match.group(3),
                    "latitude": float(match.group(5)),
                    "longitude": float(match.group(6)),
                    "name": match.group(7).strip(),
                    "state": match.group(8).strip(),
                }
            )
    return rows


def _distance2(station: dict[str, object], centre: tuple[float, float]) -> float:
    return (float(station["latitude"]) - centre[0]) ** 2 + (
        float(station["longitude"]) - centre[1]
    ) ** 2


def _parse_archive(
    data: bytes, columns: tuple[str, ...], start_year: int, end_year: int
) -> tuple[dict[datetime, float], int]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        product = next(
            name
            for name in archive.namelist()
            if "produkt" in name.lower() and name.endswith(".txt")
        )
        text = archive.read(product).decode("latin-1")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    values: dict[datetime, float] = {}
    rejected = 0
    for raw in reader:
        row = {key.strip(): (value.strip() if value else "") for key, value in raw.items() if key}
        stamp = row.get("MESS_DATUM")
        key = next((candidate for candidate in columns if candidate in row), None)
        if not stamp or not key:
            rejected += 1
            continue
        # Solar archives append the minute (for example 2021010101:10). DWD defines
        # this as the labelled observation hour; retain the hour without shifting it.
        timestamp = datetime.strptime(stamp[:10], "%Y%m%d%H").replace(tzinfo=timezone.utc)
        if not start_year <= timestamp.year <= end_year:
            continue
        try:
            value = float(row[key])
        except ValueError:
            rejected += 1
            continue
        if value <= -999:
            rejected += 1
            continue
        values[timestamp] = value
    return values, rejected


def fetch_weather(
    data_root: Path, start_year: int = 2021, end_year: int = 2025
) -> list[WeatherProfile]:
    """Capture the nearest historical DWD station per region and variable."""
    profiles = []
    client = httpx.Client(timeout=60, follow_redirects=True)
    try:
        for variable, (folder, code, columns) in DATASETS.items():
            base = f"{BASE}/{folder}"
            station_text = client.get(f"{base}/{code}_Stundenwerte_Beschreibung_Stationen.txt").text
            listing = client.get(f"{base}/").text
            archives = re.findall(r'href="([^"]+\.zip)"', listing)
            available = {
                match.group(1): name
                for name in archives
                if (match := re.search(r"_(\d{5})_", name))
            }
            candidates = [
                station
                for station in _stations(station_text)
                if station["id"] in available and int(station["end"][:4]) >= end_year
            ]
            if not candidates:
                raise RuntimeError(f"DWD {variable} has no station covering the requested period")
            for region_id, centre in REGION_CENTRES.items():
                station = min(candidates, key=lambda item: _distance2(item, centre))
                url = f"{base}/{available[str(station['id'])]}"
                response = client.get(url)
                response.raise_for_status()
                values, rejected = _parse_archive(response.content, columns, start_year, end_year)
                ordered = sorted(values)
                expected = (
                    int((ordered[-1] - ordered[0]).total_seconds() // 3600) + 1 if ordered else 0
                )
                missing = expected - len(ordered)
                reasons = []
                if not values:
                    reasons.append("no usable hourly values")
                if values and len(values) < 24 * 300 * (end_year - start_year + 1):
                    reasons.append("less than 300 days per requested year")
                profile = WeatherProfile(
                    region_id,
                    variable,
                    str(station["id"]),
                    str(station["name"]),
                    float(station["latitude"]),
                    float(station["longitude"]),
                    len(values),
                    ordered[0].isoformat() if ordered else "",
                    ordered[-1].isoformat() if ordered else "",
                    0,
                    missing if values else 0,
                    rejected,
                    not reasons,
                    tuple(reasons),
                )
                SnapshotStore(data_root).capture(
                    source_id="dwd-weather",
                    publisher="Deutscher Wetterdienst Climate Data Center",
                    source_url=url,
                    content=response.content,
                    extension="zip",
                    retrieved_at=datetime.now(timezone.utc),
                    request={
                        "variable": variable,
                        "region_id": region_id,
                        "start_year": start_year,
                        "end_year": end_year,
                        "profile": asdict(profile),
                        "timestamp_semantics": (
                            "MESS_DATUM is the observation hour in UTC; solar minute suffixes are "
                            "normalized to their labelled hour without a timezone shift"
                        ),
                    },
                    truth_class="observed_public",
                    geographic_resolution="weather_station",
                    licence="DWD open data terms",
                    adapter_version="dwd-weather-v2",
                    limitations=(
                        "Weather station observations are contextual features, not grid measurements.",
                    ),
                )
                profiles.append(profile)
    finally:
        client.close()
    return profiles


def load_temperature(data_root: Path) -> dict[datetime, float]:
    """Return the hourly mean across accepted regional temperature stations."""
    by_time: dict[datetime, list[float]] = {}
    seen_archives: set[str] = set()
    candidates: list[Path] = []
    for source_id in ("dwd-weather", "legacy-dwd-live"):
        for path, manifest in captured_blobs(data_root, source_id):
            request = manifest.get("request", {})
            legacy_path = str(request.get("legacy_path", ""))
            variable = str(request.get("variable", ""))
            normalized_path = f"/{legacy_path.replace(chr(92), '/')}/"
            if variable == "temperature" or "/temperature/" in normalized_path:
                candidates.append(path)
    for path in candidates:
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen_archives:
            continue
        seen_archives.add(digest)
        values, _ = _parse_archive(payload, DATASETS["temperature"][2], 1900, 2200)
        for timestamp, value in values.items():
            by_time.setdefault(timestamp, []).append(value)
    return {timestamp: sum(values) / len(values) for timestamp, values in by_time.items()}
