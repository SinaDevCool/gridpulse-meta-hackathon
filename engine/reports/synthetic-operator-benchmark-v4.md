# Synthetic operator benchmark V4 audit and execution

Generated 2026-08-16. All package values described here are
`synthetic_benchmark`. They are not anonymized operator measurements, real
network results, available connection capacity or evidence of feasibility.

## Duplication audit

The repository already contained most electrical and flexibility mechanics.
They were reused rather than rebuilt:

| Capability | Existing authority | Audited coverage | V4 action |
| --- | --- | --- | --- |
| Berlin geographic anchors | `grid_data/berlin_synthetic_capacity.py` | 16 public map anchors, 15 non-slack candidates | Reused unchanged |
| Synthetic topology and ratings | `build_berlin_synthetic_model()` | Meshed 110-kV mock topology, explicit impedance and kA assumptions | Reused through `synthetic_network_families()` |
| Network diversity | `capacity_backtest/backtest.py` | Eight connected topology/rating families | Reused unchanged |
| AC N-0/N-1 solver | `grid_data/network_study.py` | Pandapower thermal, voltage, convergence and islanding checks | Reused unchanged |
| Contingency selection | `capacity_backtest/graph.py` | Path, incident, bridge and thermally narrow candidates with exhaustive audit | Reused unchanged |
| Benchmark truth and release gates | `capacity_backtest/backtest.py` | 640 cases, unseen-family evaluation and conservative failure gates | Reused unchanged |
| Annual flexibility dispatch | `grid_data/deflex.py` and `capacity_backtest/flex_study.py` | 1,600 results across 10/25/50/100/200 MW | Reused unchanged |
| Public-risk coupling | `capacity_backtest/scenario_coupling.py` | Selects a mock stress class but cannot create nodal MW | Reused unchanged |
| Evidence/network contracts | `contracts.py`, `network_contracts.py`, `gridcare_outputs.py` | Truth-class and four-layer capacity boundary | Reused unchanged |

Three older synthetic paths remain intentionally separate and were not copied
into the new package: the deterministic single-request screen in
`grid_data/synthetic_capacity.py`, the Thyrow demonstration in
`fifty_hertz_synthetic_capacity.py`, and the public-geography regional
screening in `fifty_hertz_regional_screening.py`. They serve different scoped
demonstrations and are not operator-package inputs.

## Gap found

Before V4 there was no single versioned dataset joining:

- reusable topology and rating records;
- annual operating-state rows;
- publication-aware outage revisions;
- chronological connection requests and prior reservations;
- one-to-one synthetic connection-study outcomes;
- the existing DeFlex contract assumptions.

Queue commitments and outcomes were mentioned only as missing operator inputs.
Outage adapters represented real publications but could not be allocated to
the synthetic Berlin nodes. The new module fills this workflow-testing gap
without changing the public-data admission pipeline or representing mock data
as operator evidence.

## Implemented package

`capacity_backtest/synthetic_operator.py` consumes the committed benchmark
records and the same eight network-family builder. It creates six linked gzip
JSONL tables and a content-hashed manifest in OneDrive.

The annual execution is:

- run ID: `e745adb02b881e0a`;
- period: 2026-01-01 00:00 UTC for 8,760 hours;
- demand reference: SimBench 1.6.2 scenario 0 `BL-H_pload`, aggregated
  from 15-minute values to hourly means;
- demand-profile SHA-256:
  `966ace860b4e51ba1a297c5b067ce2c450d2ecccd5ec32e337ec5fb4bea284af`;
- network families: 8;
- unique benchmark candidates: 15;
- requests per candidate-family case: 4;
- total rows: 702,317;
- compressed table bytes: 16,077,994.

| Table | Rows | Purpose |
| --- | ---: | --- |
| Network assets | 376 | Versioned buses, branches and explicit synthetic ratings |
| Hourly operating states | 700,800 | Synthetic nodal demand and time-varying AC-derived N-0/N-1 envelopes |
| Outage revisions | 496 | Two publication-ordered revisions for each mock planned event |
| Queue requests | 320 | Chronological requested MW/MVA, power factor and prior reservations |
| Study outcomes | 320 | Approved-firm, conditional or rejected synthetic decisions |
| Flexibility contracts | 5 | 10/25/50/100/200 MW DeFlex policies |

Hourly asset loading is deliberately null. The package does not manufacture
branch-flow percentages from the annual envelope. A future hourly AC/state
estimation extension must solve those flows explicitly.

## Chronological queue and outcome logic

Requests are issued in deterministic timestamp order. Each decision uses the
paired annual-median synthetic N-1 envelope and only reservations created by
earlier decisions at the same synthetic node. Outcomes occur 30 days after
submission. Only mock outages whose publication time is no later than the
decision are linked as known evidence.

The generated sample contains:

- 25,595 MW of requested synthetic demand;
- 119 firm approvals totaling 5,220 MW;
- 55 conditional offers totaling 3,869.312 MW;
- 146 synthetic constraint rejections;
- 89 outcomes with one or more publication-time-known mock outage links.

These totals demonstrate queue exhaustion behavior. They do not describe any
real Berlin queue, reservation or connection offer.

## Truth and leakage controls

- Every table row is `synthetic_benchmark` and `capacity_claim: false`.
- Manifest-level `available_capacity_mw` is null.
- The package cannot be marked operator validated.
- Outage revisions are contiguous and publication ordered.
- Requests and outcomes have unique one-to-one identifiers.
- Decisions must occur after submission.
- Later decisions consume earlier synthetic reservations; later outcomes never
  modify an earlier prediction-time state.
- Public events are not assigned to synthetic nodes.
- Geographic anchors remain public map context; electrical values remain mock.

## Storage and verification

The package is stored outside Git at:

`C:\Users\sinak\OneDrive\GridPulse Capacity Research Data\simulations\synthetic-operator-package-v1\e745adb02b881e0a`

The verifier checks the six-table inventory, path containment, gzip row counts,
byte lengths, SHA-256 hashes, truth class and null confirmed-capacity field.

## Remaining boundary

This package completes the synthetic workflow benchmark, not the real-network
model. Promotion still requires operator topology, normal/emergency ratings,
historical nodal loading, switching state, outage history, queue/reservation
state and historical study decisions. Operator data must enter through the
separate `operator_model_unvalidated` boundary and cannot overwrite this
synthetic benchmark.
