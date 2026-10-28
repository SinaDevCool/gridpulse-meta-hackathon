"""Generate traceable regional reports without allocating national measurements to nodes."""

from __future__ import annotations

from pathlib import Path

from .regions import load_regions
from .storage import captured_blobs


def write_regional_reports(root: Path, report: dict[str, object], *, data_root: Path) -> list[Path]:
    profiles = []
    seen: set[tuple[str, str, str]] = set()
    for source_id in ("dwd-weather", "legacy-dwd-live"):
        for _, manifest in captured_blobs(data_root, source_id):
            request = manifest.get("request", {})
            legacy = request.get("legacy_manifest", {})
            profile = request.get("profile") or legacy.get("profile")
            if not isinstance(profile, dict):
                continue
            key = (str(profile["region_id"]), str(profile["variable"]), str(profile["station_id"]))
            if key not in seen:
                profiles.append(profile)
                seen.add(key)
    outputs = []
    for region in load_regions(root / "config" / "regions.yaml"):
        weather = [item for item in profiles if item["region_id"] == region.id]
        direct = [item for item in weather if item["accepted"]]
        rejected = [item for item in weather if not item["accepted"]]
        destination = root / "reports" / f"regional-{region.id.lower()}.md"
        destination.write_text(
            f"# {region.name} public-context stress report\n\n"
            "## Decision boundary\n\n"
            "- Available connection capacity: **Unknown**\n"
            "- Grid feasibility: **Not established**\n"
            "- Truth class: **Derived public context and synthetic scenarios**\n"
            "- Operator confirmation required: **Yes**\n\n"
            "## Geographic evidence\n\n"
            f"- Direct accepted DWD station series: {len(direct)}\n"
            f"- Quarantined DWD series: {len(rejected)}\n"
            "- Load and generation context: Germany-Luxembourg bidding zone; shared upstream "
            "context, not a regional measurement.\n\n"
            "## Weather sources\n\n"
            + "\n".join(
                f"- {item['variable']}: {item['station_name']} ({item['station_id']}); "
                f"{'accepted' if item['accepted'] else 'quarantined'}; {item['rows']:,} rows"
                for item in weather
            )
            + "\n\n## Forecast evaluation\n\n"
            + "\n".join(
                f"- {fold['test_year']}: MAE {fold['mae_mw']:.1f} MW; RMSE {fold['rmse_mw']:.1f} MW"
                for fold in report["rolling_origin_ridge"]
            )
            + "\n\nThese errors measure shared bidding-zone load prediction. They are not errors "
            "in regional or substation available-capacity estimates.\n",
            encoding="utf-8",
        )
        outputs.append(destination)
    return outputs
