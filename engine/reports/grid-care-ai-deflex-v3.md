# Grid Care AI DeFlex V3 execution report

Generated 2026-08-16. Every electrical-network and flexibility value in this
milestone is a `synthetic_benchmark`. Public publications do not establish
nodal loading, headroom, connection feasibility, or available connection MW.

## Implemented scope

- Reused the existing publication-aware 50Hertz event dataset and rolling
  control-area risk models instead of creating a duplicate pipeline.
- Added immutable capture and fail-closed quality reporting for the newly
  researched 50Hertz, E.DIS, SMARD, VNBdigital, Stromnetz Berlin, NRM, DWD,
  SimBench and ENTSO-E reference publications.
- Added complete 50Hertz vertical-grid-load archive discovery, capture and
  profiling.
- Added a versioned network-evidence package with strict identity, timestamp,
  unit, limit and provenance validation.
- Added a CGMES package integrity/profile inventory gate for EQ, SSH, TP and SV.
- Expanded the synthetic benchmark from four to eight connected network
  families while retaining at least ten routine candidates and stratified
  exhaustive N-1 audits.
- Expanded graph contingency selection to include weighted paths, incident and
  bridge assets, and thermally narrow branches. AC power flow remains
  authoritative.
- Replaced constant annual DeFlex envelopes with deterministic time-varying
  hourly mock envelopes.
- Added critical/flexible load separation, workload deadlines, ramp-shortfall
  accounting, battery degradation, reserve SOC, recovery, rebound and separate
  critical/flexible unserved energy.
- Added a conservative regional-risk-to-mock-scenario contract that cannot
  generate a physical MW adjustment.
- Added an executable four-layer Grid Care AI output contract.

## OneDrive data execution

Durable artifacts are stored under:

`C:\Users\sinak\OneDrive\GridPulse Capacity Research Data`

The repository contains no raw downloads. Seven newly researched publication
captures succeeded:

| Source | Bytes | SHA-256 | Result |
| --- | ---: | --- | --- |
| 50Hertz vertical-load page | 164,620 | `8eb2a5b...13146b` | Captured |
| SMARD download centre | 20,856 | `b8d8626a...ef425` | Captured |
| E.DIS/VNBdigital 2024 plan | 8,254,244 | `819cf2b8...ea348` | Captured |
| Stromnetz Berlin repartition page | 131,797 | `5b572e5d...a4691` | Captured |
| NRM pro-rata page | 192,359 | `ec868c41...a308` | Captured |
| DWD HOSTRADA description | 28,390 | `31e06778...9977` | Captured |
| ENTSO-E CGMES library | 92,832 | `ea623c10...57647` | Captured |

Two endpoints were not accessible through the tested unauthenticated download:

- E.DIS redispatch forecast page returned an authentication barrier. Existing
  E.DIS RSS/legacy service evidence remains separate and no successful page
  download is claimed.
- The SimBench documentation PDF endpoint returned source unavailable. The
  installed versioned SimBench package remains the executable reference; no
  documentation snapshot is fabricated.

### 50Hertz vertical-grid-load archive

The official file-list API returned 15 CSV archives covering 2012 through the
partial year 2026. All were stored as immutable content-addressed snapshots.

- Downloaded bytes: 29,814,278.
- Parsed quarter-hour records: 512,743.
- Repeated local timestamp labels: 56, consistent with autumn DST labels that
  lack an explicit UTC offset/fold marker.
- The 2023 file contains 35,031 records and the 2025 file 35,004, below the
  expected 35,040 real quarter-hours for a complete non-leap year.
- The files use Europe/Berlin local labels without an explicit offset.
- Values are MW at 50Hertz control-area resolution, including negative vertical
  load; they are not distribution-node measurements.

The archive therefore remains unavailable for publication-time-aware training
until DST folds, absent intervals, publication timing, revision retention and
reuse rights are resolved. It is admissible as profiled control-area context.

## Network-model contract

The JSON contract requires:

- schema, model and version identifiers;
- timezone-aware effective time;
- unique buses and assets;
- validated connectivity references;
- explicit operational-limit values and units;
- source URL, retrieval time, snapshot hash, licence and geography;
- a truth class and explicit operator-validation flag.

A synthetic package cannot be marked operator validated. An
`operator_confirmed` package fails unless explicit validation is present. Even a
valid package reports `available_capacity_mw: null` because network validation
alone is not a connection offer.

CGMES inspection verifies ZIP integrity and the presence of EQ/SSH/TP/SV XML or
RDF members. It does not yet assert CIM semantic consistency, solved-state
reproduction, historical switching state, or operator approval, so its output
is always `operator_model_unvalidated`.

## Mock electrical model and DeFlex method

The eight network families are connected variants of the geographically
anchored synthetic 110 kV benchmark. Their electrical parameters remain mock
parameters. Public maps supply anchors only; SimBench/CGMES conventions supply
reference structure and interoperability conventions.

For each node and operating scenario, pandapower calculates AC N-0 and N-1
thermal, voltage, convergence and islanding constraints. Graph selection never
calculates MW. Exhaustive cases remain the audit truth.

The DeFlex study evaluates 10, 25, 50, 100 and 200 MW site scenarios with:

- an 80% continuous critical-load floor;
- a bounded daily shiftable workload profile;
- 10% maximum interruptible fraction;
- four-hour maximum consecutive interruption;
- 120-hour annual interruption budget;
- four-hour recovery/rebound policy;
- battery power equal to 25% of site MW and energy equal to one site-load hour;
- 92% charge and discharge efficiency;
- 10% minimum reserve SOC;
- a planned import ramp limit of 50% of site MW per hour;
- no assumed backup generation.

Hourly demand and network envelopes vary deterministically with daily and
seasonal stress. These are reference-inspired mock scenarios, not reconstructed
regional loading. Flexibility never multiplies an N-1 envelope. Dispatch is
chronological and explicitly bounded by the AC-derived mock envelope, battery
physics, interruption, recovery and ramp constraints.

## Four output layers

1. Public context: operator-published evidence at its source resolution.
2. Regional probability: experimental estimate with release status.
3. Synthetic DeFlex: mock electrical/flexibility result with no capacity claim.
4. Operator-confirmed capacity: unavailable, MW null.

The output validator rejects truth-class promotion, blending and a synthetic
capacity claim.

## Information still required

The decisive real-network model remains externally blocked pending operator
data. Required fields are:

- anonymized connectivity and stable equipment identifiers;
- normal and emergency ratings valid at each historical time;
- hourly or quarter-hourly loading, voltage and topology/switch states;
- planned and unplanned outage history;
- protection and applicable N-1 policy;
- contracted, queued and reserved demand;
- anonymized connection requests and requested MW/MVA/power factor;
- assessed connection point and approved/rejected/conditional outcome;
- firm/conditional MW offered, reinforcement and delivery timing.

Data-centre owners must separately supply critical and shiftable workload,
deadlines, UPS/battery telemetry, efficiencies, degradation, ramping, backup
availability and service-level penalties. Public assumptions remain synthetic.

## Release status

- Public constraint context: available at published resolution.
- Experimental 50Hertz risk: available; operational release gate failed.
- Synthetic DeFlex: benchmark execution completed; both synthetic release
  gates failed, and it is never a real-network result.
- Operator-model result: unavailable until a validated package is supplied.
- Operator-reconciled result: unavailable.
- Operator-confirmed capacity: unavailable; MW remains null.

## Completed benchmark and DeFlex results

The expanded benchmark evaluated 640 cases across eight held-out synthetic
network families and 15 unique candidate nodes. It produced:

- mean/median absolute error: 58.742 / 43.0 MW;
- overstatement/severe-overstatement rate: 21.9% / 16.2%;
- interval coverage: 85.0%;
- top-10 recall: 22.5%;
- contingency-selector recall: 29.7% over 64 exhaustive audit cases;
- graph contingency reduction: 83.9%.

The ranking and capacity-band release gates both failed. These metrics are for
mock electrical networks and must not be interpreted as errors or capacity on
the real Berlin grid.

The deterministic DeFlex run produced 1,600 synthetic node/scenario/site
results (320 cases for each of 10, 25, 50, 100 and 200 MW). Across the mock
operating uncertainty, constrained-hour ranges were respectively 0-0,
0-5,260, 0-8,760, 0-8,760 and 0-8,760 hours. Maximum unserved energy ranged
from 0 MWh for 10 MW to 1,396,325.568 MWh for 200 MW. The wide range is a
warning about scenario and topology sensitivity, not a regional forecast.

## Verification record

- `pytest -q`: 110 passed;
- repository-wide Ruff lint: passed;
- changed-file Ruff formatting: passed;
- repository-wide formatting: 23 pre-existing files remain unformatted and
  were intentionally left outside this milestone;
- immutable cloud-manifest verification: 1,200 checked, zero failures;
- changed/new-file credential scan: no credential-like patterns found;
- four-layer output validation: passed, all available-capacity MW fields null;
- complete expanded AC N-0/N-1 benchmark: completed successfully.

The OneDrive store inventory at verification contained 1,977,269,303 raw
bytes, 580,613,488 normalized bytes, 74,840,914 feature bytes, 86,441,348
prediction bytes and 1,200 verified manifests. Raw source files were not added
to Git. Commit hashes and the pushed branch are recorded in the delivery
message because a commit cannot truthfully contain its own final hash.
