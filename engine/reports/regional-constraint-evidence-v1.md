# Regional Constraint Evidence V1

## Release decision

No researched source is admitted to regional constraint-model training yet. This is a
fail-closed result, not evidence of zero congestion. The event schema, temporal dataset builder,
metrics and fixture-tested interfaces are ready, but real backtest scores remain **unavailable**.
Berlin and Brandenburg nodal loading, headroom and available connection MW remain **unknown**.

## Research findings (primary publishers, checked 2026-08-16)

- E.DIS publishes a downloadable table of completed actions with start/end, area, constraint
  location, cause and operator fields. It is the best regional candidate, but no immutable
  publication/revision archive or open reuse licence was identified.
- The German TSOs publish redispatch through Netztransparenz, including a 2013-2020 archive.
  Coverage changes at October 2021 and October 2023 and the live table may be revised.
- 50Hertz states that current measures are published directly from its Redispatch call server,
  but retained publication revisions and a stable DSO-regional mapping remain unverified.
- ENTSO-E supports A63 redispatch and unavailability documents with document identifiers and
  revisions. The standard extraction flow has not been proven to reproduce every version known
  at an old issue time, so it remains quarantined.
- SMARD data are CC BY 4.0 and downloadable, but the redispatch series are continuously updated
  and geographically too coarse to become measured Berlin/Brandenburg labels.
- Stromnetz Berlin and NRM describe Redispatch 2.0 processes and RAIDA exchange, but expose no
  public historical event feed found in this audit. wesernetz exposes current measures, not a
  reconstructable history.
- Bundesnetzagentur warns that congestion-management submissions are updated after reporting;
  missing or absent rows therefore cannot safely be interpreted as zero events.

Exact metadata and admission decisions are machine-readable in
`config/source_admissibility.yaml`.

## Implemented boundary

`grid-event-v1` preserves source and record IDs, event and revision IDs, retrieval/publication/
start/end timestamps, operator and geographic scopes, assets, direction, nullable MW/MWh,
reason/status, match confidence, truth class, URL, snapshot hash and validation warnings.
Historical features select only the latest revision published by the issue time. Missing MW stays
null. Targets remain null whenever source availability or revision completeness is unverified.

## Model status

The historical-event-rate rolling baseline and calibration-sensitive metrics are implemented.
Logistic, tree, Platt, isotonic and TabPFN comparisons are intentionally not executed against
fixtures or incomplete public histories. Consequently event counts, real geographic coverage,
yearly precision/recall/PR-AUC/ROC-AUC/Brier/calibration, and operational reliability are all
**unavailable**. The regional release gate is **FAIL**.

## Data captured

No new raw dataset was downloaded during this milestone. Downloaded size: **0 bytes**. The
configured durable location remains the OneDrive-backed `data/raw/` tree; only immutable hashes
and manifests may enter processing. No source tokens are stored in the repository.
