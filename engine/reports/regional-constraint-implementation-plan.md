# Regional Constraint Evidence V1 implementation plan

## Audited baseline

- Baseline: `c767b3ba91a6834c89c8c3861b3555f01ae54a7c`, clean branch
  `codex/capacity-backtest-foundation`; 61 tests passed in 337.31 seconds.
- Source capture: `download.py`, `entsoe.py`, `dwd.py`; immutable raw artifacts and manifests.
- Lineage/quality: `contracts.py`, `lineage.py`, `profiling.py`, `quality.py`, `audit.py`.
- Forecasting: `timeseries.py`, `models.py`, `validation.py`, `live_backtest.py`.
- Event handling: the former `events.py` contained only a small revision selector and three
  active-event features; it had no source identity, retrieval time, geographic confidence or hash.
- Identity/geography: `identity.py` and `regions.py` propose reviewable names/coordinates and
  point-in-polygon matching; no unresolved Berlin node is treated as official.
- Synthetic physics: `grid_data/network_study.py` is authoritative for synthetic AC values;
  `graph.py` selects contingencies but does not calculate MW.
- Flexibility: `scenarios.py` and `activatable_capacity.py` were disconnected from synthetic AC
  hourly envelopes. `validation.py` applied a coarse national-load scenario.
- Release: `sufficiency.py`, `contracts.py`, and backtest gates fail closed, although
  `CALCULATED_VALIDATED` previously could pass the generic capacity-claim assertion.

## Audit issues addressed

- Correct stale 2023 stress precision text from 1.2% to the committed 16.7% result.
- Replace the hidden two-node/two-scenario benchmark truncation with a documented deterministic
  ten-node structural sample, all four operating scenarios and four network families.
- Add the canonical event schema, source admission contract and null-preserving regional features.
- Couple five data-centre sizes to paired synthetic AC N-0/N-1 envelopes through hourly bounded
  interruption, battery, recovery and ramp dispatch.
- Narrow confirmed available-capacity claims to `operator_confirmed` evidence only.

## Deliberately unfinished because evidence is unavailable

- No real regional classifier or calibration model will be fit until a source passes every
  publication-time, revision, identity, completeness, unit and reuse gate.
- ENTSO-E outage/redispatch, E.DIS, Netztransparenz and 50Hertz adapters remain research adapters,
  not admitted training feeds, until immutable historical versions can be reconstructed.
- Operator outcome calibration and operator-confirmed capacity remain unavailable.
