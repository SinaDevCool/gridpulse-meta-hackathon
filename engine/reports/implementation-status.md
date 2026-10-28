# Regional capacity research implementation status

## Implemented

- OneDrive-backed durable research storage and local volatile working storage.
- Source-specific immutable snapshots with content hashes.
- Source registries for national, Berlin, benchmark and regional operator context.
- Explicit Berlin, Brandenburg, Bremen, Frankfurt and Rhine-Main study scopes.
- Leakage-safe hourly lag construction and chronological held-out-year splitting.
- Transparent regression baselines and a fail-closed Prior Labs TabPFN adapter.
- Physical battery power/energy constraints and 8,760-hour scenario validation.
- Neo4j-compatible graph exports; graph results never claim capacity.
- Pandapower synthetic N-0/N-1 capacity benchmarking and evidence gates.
- Semantic ENTSO-E profiling that quarantines incompatible units, resolutions, directions,
  duplicate timestamps and incomplete series before modelling.
- Complete 2021-2025 Germany-Luxembourg actual-load and monthly generation snapshots.
- Lag-only wind and solar features, four rolling yearly holdouts, and labelled annual stress
  scenarios that never claim available capacity.
- DWD temperature, wind and solar station capture for five study scopes with UTC, coverage and
  missing-value profiles. Frankfurt and Rhine-Main solar fail the complete-period gate.
- Publication-time-aware event contracts for outage/congestion revisions; unavailable events are
  never represented as zero.
- Rechargeable battery and 5%/10% demand-response scenarios for 50, 100 and 200 MW site loads.
- Five regional reports that keep local weather evidence distinct from shared bidding-zone data.

## Current external limitations

- Prior Labs and ENTSO-E authenticated execution were verified on 2026-08-13. Credentials remain
  external to the repository and must be supplied by the operator of each run.
- ENTSO-E load is published for the Germany-Luxembourg bidding zone, not for the requested cities,
  distribution nodes or substations.
- Public sources do not provide complete live loading, ratings, switching state, queue,
  reservation, outage, protection and N-1 policy data for each real distribution node.
- Therefore live available MW at Berlin, Brandenburg, Bremen or Rhine-Main substations
  remains unknown and requires operator evidence.
- Existing synthetic benchmark release gates remain failed and must not be represented as
  production validation.

## Next executable data milestone

The 2021-2025 Germany-Luxembourg load and generation series have been captured from ENTSO-E.
All 65 admitted artifacts passed source-aware semantic and timestamp checks. A frozen 2025
out-of-sample evaluation gives ridge MAE 1,313.6 MW with lagged wind/solar context versus
1,336.0 MW without it. Adding lagged DWD temperature reduces ridge MAE to 1,296.8 MW; the
authenticated Prior Labs benchmark reaches 452.4 MW. Rolling ridge MAE is 1,220.9 MW (2022),
1,233.0 MW (2023), 1,261.2 MW (2024) and 1,296.8 MW (2025), showing temporal drift.

The experimental high-load classifier fails its release gate: recall is high but precision is
unstable and falls to 16.7% in 2023. Congestion/outage inputs remain unavailable because historical
publication revisions and stable asset correspondence are not yet validated. Regional or nodal
capacity remains unknown until operator-grade evidence is available.

## Regional Constraint Evidence V1 (2026-08-16)

- Added `grid-event-v1`, strict source admission decisions, UTC/DST-safe revision selection,
  regional hourly rows, historical/seasonal/logistic baselines, prior-only Platt and isotonic
  calibration, rare-event metrics, identity collision review, and explicit release gates.
- Researched E.DIS, 50Hertz/Netztransparenz, ENTSO-E, SMARD/Bundesnetzagentur, Stromnetz Berlin,
  wesernetz and NRM primary publications. No candidate yet passes the complete historical
  publication/revision, identity, units, empty-response and reuse gate; no real regional model was
  trained and no new raw data was downloaded.
- Expanded the synthetic benchmark to 320 AC records, four network families, four operating
  scenarios and a per-family ten-node structural sample whose union covers all 15 non-slack nodes.
  Ranking and capacity gates still fail; contingency-selector recall is 18.8%.
- Added 800 synthetic annual DeFlex-style dispatch summaries for 10/25/50/100/200 MW loads. These
  remain synthetic and are not evidence of Berlin capacity.
