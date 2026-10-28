# GridPulse Capacity Backtest Lab

An independent research project for testing whether public and operator-approved evidence can support conservative grid-capacity screening.

The backend also includes an evidence-cutoff-safe operator-territory pipeline for reproducible
site-location capture, versioned DSO polygons, MaStR identity reconciliation, private-network
exceptions, scoped operator confirmation, PCC admission, and historical safety metrics. See
`docs/operator-territory-backtest.md`.

This repository is self-contained. Selected calculation modules were copied from GridPulse rather than imported from its working tree. Their precise origin and hashes are recorded in `PROVENANCE.md` and `data/manifests/copied-grid-data.sha256`.

## Safety boundary

- Public mapping does not establish connection capacity or feasibility.
- Synthetic studies are demonstrations, not observations of a live network.
- Missing data remains unknown.
- Any capacity result must retain its truth class and provenance.
- Operator confirmation is required before a result may be represented as available capacity.

### Facility optimiser qualification — not an Operations deployment

The canonical facility MILP remains in `data_center/optimizer.py`; the web scenario
heuristic must not be presented as this solver. Sparse assembly and solver-result
checks live in `data_center/solver_support.py`, not a second optimisation engine.

- The optimiser forbids simultaneous battery charging and discharging, includes
  cooling load in the meter balance, and prices purchased facility electricity
  (including battery charging), rather than GPU electricity alone.
- `objective_eur` excludes numerical tie-breaking coefficients.
  `solver_objective_eur`, `objective_bound_eur` and `optimality_gap` describe the
  perturbed solver objective, not a bound on the separately reported economic cost.
- A time/iteration limit is not proof of infeasibility. A limit-reached incumbent
  must pass finite-value, bounds, integrality, linear-constraint and physical replay
  checks before receiving `feasible_not_proven_optimal`. Existing uncertainty
  admission remains conservative and does not treat this status as proven optimal.
- Physical replay rejection remains `replay_failed`; no result authorises dispatch.
- Model identity includes empirical profiles, onsite generation and fatigue limits.
  Only uniform planning intervals are currently supported by this formulation.

Qualification regressions: `tests/test_optimizer_solver_qualification.py`.

Remaining release gates are deliberately **not** claimed complete: full workload
continuity/resource-capacity modelling, genuine state-carrying rolling replanning,
non-anticipative uncertainty decisions, reviewed site/tariff data, independent
historical/shadow validation, and an approved versioned engine artifact/runtime.
The application adapter also needs explicit battery transport qualification before
an uploaded web request can be called a joint battery-and-workload plan. This change
does not enable PR #37, change Supabase, publish an engine package, or deploy a service.

## Included foundation

- Explicitly parameterised AC network studies with N-0/N-1 checks.
- Synthetic Berlin and 50Hertz-area study adapters.
- Regional screening and pre-application packaging.
- Public-source parsers and capacity-observation validation.
- Deterministic activation-envelope calculations.
- Focused tests copied with the calculation modules.

The GridPulse web application, Supabase integration, Cloudflare deployment, UI, and browser state are intentionally excluded.

## Phase 0 architecture

Phase 0 introduces canonical, versioned contracts under `capacity_backtest.domain` and the
fail-closed `StudyPipeline`. All new capacity methods must use these contracts rather than
creating another untyped scenario or result format. See `docs/phase0-architecture.md` for the
ownership rules, pipeline gates, artifact requirements, and golden conformance suite.

Phase 1 adds bottom-up probabilistic forecasting, chronological AC N-0/N-1 envelopes,
physics-only surrogate screening, risk-limiting policy backtests, and horizon-specific study
contracts. See `docs/phase1-capacity-foundation.md` for methods and remaining evidence limits.

Phase 2 adds stateful battery, cooling and workload recovery, fatigue gates, evidence-weighted
resource credibility, correlated non-delivery reserve, event-triggered invalidation, explicit
three-phase/reactive checks, and a governed dependable conditional envelope. See
`docs/phase2-dependable-capacity.md`.

Phase 3 adds a PCC telemetry gate, bounded P/Q feedback, authorized and acknowledged command
lifecycle, explicit fail-safe state machine, delivery verification, tamper-evident deterministic
replay, and separate digital-twin versus live-authorization readiness. See
`docs/phase3-operational-digital-twin.md`.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[study,dev]"
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check src tests
```

## Research sequence

1. Snapshot and hash authoritative source files.
2. Build a Berlin node and allocation-area crosswalk.
3. Reconstruct evidence without inventing residual capacity.
4. Backtest full-information and reduced-information methods on SimBench.
5. Evaluate bias, unsafe overstatement, ranking stability, and interval coverage.
6. Add operator outcomes only under a separate confidential data boundary.

The first milestone is source sufficiency and identity resolution. It deliberately stops before publishing MW estimates.

## Evidence pipeline

The `capacity_backtest` package keeps source capture, transformation lineage, and output
sufficiency separate from the inherited experimental grid models.

```powershell
python -m capacity_backtest.cli sources list
python -m capacity_backtest.cli sources fetch
python -m capacity_backtest.cli audit
python -m capacity_backtest.cli backtest
python -m capacity_backtest.cli live fetch --start-year 2021 --end-year 2026 --document-type A65
python -m capacity_backtest.cli live fetch --start-year 2021 --end-year 2026 --document-type A75 --monthly
python -m capacity_backtest.cli weather fetch --start-year 2021 --end-year 2025
python -m capacity_backtest.cli live backtest --held-out-year 2025 --tabpfn
```

Downloads are immutable, content-hashed snapshots under `data/raw/` (gitignored). Each
snapshot has a sidecar manifest. The committed evidence audit in `reports/` records which
outputs the registered evidence supports. Public topology, historical allocation,
congestion, and synthetic benchmark data do **not** establish current available MW at a
Berlin grid node.

The placeholder rows in `config/berlin_nodes.csv` deliberately remain unresolved until an
official node identity and coordinates can be cited and reviewed. Automated crosswalks can
only propose matches; they never accept one silently.

The executable backtest covers all 15 available non-slack nodes in the geographically
anchored synthetic Berlin model across four demand scenarios and N-0 plus graph-selected
representative N-1 cases. Its generated report is committed under `reports/`. The graph
layer identifies pathways and reduces physics cases; Pandapower remains authoritative for
synthetic MW calculations. This validates mechanics, not live Berlin conditions, and cannot
pass release gates without broader unseen-network and operator validation.

## OneDrive-backed research storage

Durable research data defaults to the dedicated Microsoft cloud-synchronised directory
`%OneDrive%\GridPulse Capacity Research Data`. The Git repository contains code, small fixtures,
configuration and release reports, not downloaded research data. Set `GRIDPULSE_DATA_ROOT` only
to select another deliberate durable root:

- `raw/`: immutable source snapshots
- `manifests/`: hashes, licences and provenance
- `normalized/` and `derived/`: validated transformations
- `features/`: versioned model inputs
- `models/`: approved model artefacts
- `predictions/`: strictly out-of-sample predictions
- `simulations/`: completed annual and network studies
- `exports/`: portable Neo4j, CSV and Parquet exports
- `backups/`: recoverable database and configuration backups
- `runs/`: complete capacity-study JSON, Markdown and hash manifests
- `reports/`: durable generated screening reports
- `operator-confidential/`: access-restricted operator evidence (never credentials)

The canonical available-capacity workflow is documented in
`docs/capacity-only-implementation.md`. Run the explicit mock methodology case with:

```powershell
python -m capacity_backtest.cli capacity run --study config/studies/capacity_screening_mock.yaml
```

Large contents are gitignored. Volatile caches, staging files, active model runs and the live
Neo4j database default to `C:\Users\sinak\Documents\GridPulse-Capacity-Work`, outside the
OneDrive repository. Do not put a live Neo4j database in a cloud-synchronised directory.

```powershell
python -m capacity_backtest.cli storage init
python -m capacity_backtest.cli storage show
python -m capacity_backtest.cli storage verify --require-cloud
python -m capacity_backtest.cli storage inventory
python -m capacity_backtest.cli regional capture
python -m capacity_backtest.cli regional vertical-load
python -m capacity_backtest.cli graph export
python -m capacity_backtest.cli gridcare output
python -m capacity_backtest.cli synthetic operator-package --hours 8760 --requests-per-node 4
python -m capacity_backtest.cli synthetic verify-operator-package "C:\path\to\manifest.json"
python -m capacity_backtest.cli synthetic queue-backtest "C:\path\to\manifest.json"
python -m capacity_backtest.cli synthetic contingency-audit
python -m capacity_backtest.cli synthetic hourly-ac "C:\path\to\manifest.json"
python -m capacity_backtest.cli synthetic optimized-deflex --hours 168
python -m capacity_backtest.cli operator validate-intake "C:\confidential\manifest.json"
python -m capacity_backtest.cli operator reconcile predictions.json outcomes.json
python -m capacity_backtest.cli network validate .\operator-confidential\network.json
python -m capacity_backtest.cli network inspect-cgmes .\operator-confidential\cgmes.zip
```

Completed downloads are first written to disposable local staging, copied atomically to OneDrive,
and read back for SHA-256 verification. The temporary copy is then removed. A live Neo4j database
must remain outside OneDrive; exports and backups may be cloud stored.

Set `GRIDPULSE_DATA_ROOT` or `GRIDPULSE_WORK_ROOT` to override either default. No API
credentials are stored in these directories. Prior Labs authentication is read only from
`TABPFN_TOKEN` in the process environment; ENTSO-E authentication is read only from
`ENTSOE_TOKEN`. Raw responses and predictions are gitignored, while each raw snapshot carries a
content hash and explicit limitations.

The live backtest uses Germany-Luxembourg bidding-zone load and generation. Before a snapshot
is admitted, it is profiled for document semantics, unit, resolution, direction, duplicate
timestamps, missing intervals and invalid values. Load must be one A04/A01 area-total series.
Generation and consumption are kept distinct even when ENTSO-E repeats a production-type code.
Rejected profiles fail closed before feature construction. Wind and solar enter only through
historical lags, so the frozen-year evaluation cannot see future observations.

These series are common upstream context for the configured regions, not regional or node-level
measurements. Their error metrics are load-forecast errors and must never be described as errors
in available-capacity estimates.

## Forecasting and model boundary

The research pipeline provides leakage-safe hourly feature construction, transparent mean
and ridge baselines, a fail-closed Prior Labs TabPFN adapter, physical battery scenarios,
and portable Neo4j CSV exports. TabPFN is a statistical benchmark; it does not replace AC
power flow or establish available MW. A missing `TABPFN_TOKEN` produces an explicit
`unavailable` result. Public or synthetic inputs never become operator confirmation.

The live report includes rolling-origin ridge evaluations for 2022-2025 and explicitly labelled
annual stress scenarios. Scenario MW values describe system-load context only; they are not
headroom, a connection offer, or a substation capacity estimate.

DWD historical observations are selected from the nearest station with the requested coverage,
stored as immutable hashed ZIP snapshots, and normalized to UTC. Temperature enters the forecast
only through 1, 24 and 168-hour lags. Region-specific wind and solar snapshots are retained for
regional context but are not silently substituted when a station fails the coverage gate.

The congestion/outage event contract preserves publication time and revision order. No event
source is admitted until historic revisions and asset identities can be reconstructed. Missing
events therefore remain unavailable, never zero.

## Regional Constraint Evidence V1

The V1 milestone adds a versioned canonical event record, an explicit all-prerequisites source
admission gate, publication-time regional feature construction, a rolling historical-event-rate
baseline, and calibration-sensitive classification metrics. Primary-source decisions are recorded
in `config/source_admissibility.yaml`. No researched event source currently passes every training
gate, so real regional event counts and model scores remain unavailable rather than being produced
from revised-current pages or fixtures.

The synthetic benchmark now uses a documented deterministic ten-node structural sample across all
configured operating scenarios and four synthetic network families. Its DeFlex-style study runs
hourly bounded interruption, recovery, battery and ramp dispatch for 10, 25, 50, 100 and 200 MW
site scenarios against paired synthetic AC N-0/N-1 envelopes. These outputs remain synthetic and
cannot be described as Berlin capacity.

Outputs are kept in four non-interchangeable layers: public constraint context, probabilistic
regional risk, synthetic flexibility study, and operator-confirmed capacity. The last layer remains
unavailable without operator-confirmed evidence.

## Grid Care AI mock DeFlex boundary

The expanded mock milestone uses eight connected synthetic network families, public SimBench and
CGMES conventions, time-varying hourly N-0/N-1 envelopes, and explicit critical/flexible demand,
recovery deadlines, ramping, battery reserve, degradation and unserved-energy accounting. Public
regional risk can select a conservative synthetic stress class but can never directly create a
nodal MW derating.

`network validate` checks the versioned JSON network-evidence contract. `network inspect-cgmes`
checks ZIP integrity and the presence of EQ/SSH/TP/SV profiles only; it deliberately returns
`operator_model_unvalidated` because schema inventory is not electrical or operator validation.
The default `gridcare output` command demonstrates the four-layer contract and keeps confirmed
capacity unavailable.

The synthetic operator-package command reuses the committed AC benchmark instead of creating a
second electrical model. It writes linked, content-hashed gzip JSONL tables for network assets,
hourly synthetic demand and N-0/N-1 envelopes, publication-aware mock outage revisions,
chronological queue requests, synthetic connection-study decisions and DeFlex contracts under the
OneDrive `simulations/` directory. Hourly branch loading remains null because the annual package
does not pretend that an unsolved proxy is an AC flow. Every row is `synthetic_benchmark`, and the
package always reports `available_capacity_mw: null`.

The next synthetic milestone reuses those authoritative tables. A chronological queue backtest
uses only decisions and outage revisions published before each request. The V4 contingency
selector is audited against exhaustive N-1 solutions before use. Representative hourly AC solves
record per-asset voltage and loading, while the optimized DeFlex benchmark uses a bounded HiGHS
linear program with explicit SOC, recovery, ramp and deadline constraints. Large rows and metrics
are written to the configured OneDrive data root. These commands remain synthetic experiments;
their release gates cannot establish live or confirmed connection capacity.
# Test verification

Slow integration tests are opt-in and cannot run accidentally through plain `pytest`.

```powershell
# Normal development gate (slow tests remain disabled)
.\scripts\verify.ps1 fast

# Release gate: fast tests first, then each slow file in strict order
.\scripts\verify.ps1 release

# Explicit direct slow-test execution
.\.venv\Scripts\python.exe -m pytest --run-slow -m slow
```

JUnit results are written to `reports/tests`. The release runner stops immediately if
the fast gate or any preceding slow file fails.
