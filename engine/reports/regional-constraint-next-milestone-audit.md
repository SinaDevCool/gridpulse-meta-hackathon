# Regional constraint next-milestone audit and implementation plan

Audited: 2026-08-16  
Branch: `codex/capacity-backtest-foundation`  
Audited commit: `6c16923`

## Outcome

The repository already contains the event contract, publication-time selection, regional feature
builders, temporal baselines, OneDrive storage resolver, immutable regional capture, quality
profiles, synthetic benchmark, flexibility dispatch and conservative release gates needed for the
next milestone. These components should be extended rather than replaced.

Before adding another source adapter, storage must be unified. The older ENTSO-E, DWD, prediction
and report readers still address the repository-local `data/` tree, while regional capture uses the
dedicated OneDrive root. Repeated regional captures also store identical response bytes under new
retrieval-time directories. Building the historical crawler on the present layout would multiply
data and create two competing sources of truth.

No public evidence found in this milestone establishes nodal loading, headroom, connection
feasibility or available MW. The first real model must remain a 50Hertz-control-area published
constraint-risk model.

## Verified baseline

- Git working tree was clean and synchronized with
  `origin/codex/capacity-backtest-foundation`.
- Unit tests: 87 passed.
- Ruff lint: passed.
- Ruff formatting: failed on 26 pre-existing files; this is a style baseline, not a functional
  failure.
- Durable OneDrive root:
  `C:\Users\sinak\OneDrive\GridPulse Capacity Research Data`.
- OneDrive storage health and write/read verification: passed.
- OneDrive inventory: 36 raw files / 38,749,302 bytes; one normalized file / 215,738 bytes;
  eight quality files / 11,844 bytes.
- Repository-local ignored data inventory: 193 files / 433,374,341 bytes, including 181 raw
  files. The repository itself is under OneDrive, but these data are mixed with source control and
  are not using the dedicated durable-data contract.
- Volatile work root:
  `C:\Users\sinak\Documents\GridPulse-Capacity-Work`; currently empty.
- ENTSO-E authentication is available through `ENTSOE_TOKEN`; an authenticated request returned
  HTTP 200. The token was not read into reports or source files.

## Existing components to reuse

| Concern | Existing authority | Required extension |
|---|---|---|
| Storage selection and safety | `capacity_backtest/storage.py` | Add a single content-addressed snapshot store and migration inventory. |
| Generic HTTP capture | `capacity_backtest/regional_ingest.py` | Route every downloader through the shared snapshot store; add retries, backoff and request metadata. |
| Source registry | `config/sources/*.yaml`, `regional_ingest.PUBLIC_ENDPOINTS` | Replace the second hard-coded registry with one typed registry or a generated adapter map. |
| Canonical events | `capacity_backtest/events.py` | Reuse `GridEvent`; add source-specific parsers without creating another event dataclass. |
| 50Hertz revision logic | `capacity_backtest/fifty_hertz.py` | Extend the parser to historical HTML/CSV and outage records. |
| Publication-time features | `capacity_backtest/events.py`, `regional_constraints.py` | Reuse `known_events` and `build_regional_rows`; add lead-time targets and availability intervals. |
| ENTSO-E load/generation | `capacity_backtest/entsoe.py` | Keep A65/A75 behavior; create event-document parsing for A63/A78 rather than overloading the time-series assumptions. |
| Identity | `identity.py`, `regional_identity.py`, `regions.py` | Add asset aliases, collision review and authoritative area geometry, retaining regional-only matches. |
| Admission and quality | `admissibility.py`, `quality.py`, `config/source_admissibility.yaml` | Generate decisions from measured profiles instead of manually duplicating status in reports. |
| Reports | `regional_reports.py`, committed JSON/Markdown reports | Introduce one machine-readable run summary that generates all human-readable summaries. |
| Temporal modelling | `regional_constraints.py` | Add regularized tree baseline and explicit yearly/season/operator/missing-source reports. |
| Synthetic/flexibility | `backtest.py`, `flex_study.py`, `grid_data/deflex.py` | Preserve as a separate synthetic output layer; do not couple public control-area events to synthetic nodes. |

## Duplication and disconnection findings

### Two durable-data paths

`cli.py` sends new source capture, weather downloads, graph exports and ENTSO-E fetches to the
resolved OneDrive root. However, `live_backtest.py` and `regional_reports.py` still read
`<repository>/data/raw`, and live predictions are written to `<repository>/data/predictions`.
Consequently, a new cloud download is not necessarily the data read by the existing backtest.

Resolution: every reader and writer must accept a `StorageLayout` or explicit `data_root`. No
runtime module may construct `<repository>/data` directly except the documented local fallback
when OneDrive is unavailable and cloud storage was not required.

### Duplicate immutable payloads

Five duplicate-content groups are already present in the dedicated OneDrive raw store: the
Netztransparenz archive, both Stromnetz Berlin workbooks and both wesernetz CSVs were each stored
twice. The duplicate captures are legitimate retrieval observations, but storing the same payload
bytes twice is unnecessary.

Resolution: separate payload identity from capture identity:

```text
raw/blobs/sha256/<first-two>/<full-sha256>.<extension>
manifests/captures/<source-id>/<yyyy>/<mm>/<timestamp>-<request-hash>.json
```

Each capture manifest records retrieval time, URL, request parameters, safe response headers,
status, byte length and the referenced blob hash. Identical responses create new capture manifests
but reuse one blob. A source response that changes creates a new blob. This preserves the complete
observation history without duplicate payload storage.

Existing snapshots must not be deleted during migration. Build an inventory, copy or hard-link only
where safe, verify every hash, write a migration manifest, and switch readers. Removal of legacy
copies is a later, explicit and recoverable cleanup after OneDrive sync and manifest verification.

### Multiple manifest conventions

The dedicated `manifests/` directory is empty even though manifests are stored beside raw
artifacts. ENTSO-E, DWD, generic downloads and regional downloads use different manifest shapes and
write methods. The execution report counts sidecar manifests while the storage inventory reports
zero files in `manifests/`.

Resolution: define `snapshot-manifest-v2` once, keep source-specific metadata in a namespaced
section, and store capture manifests in `manifests/captures`. Keep compatibility readers for v1
sidecars during migration.

### Competing source registries

The YAML registries describe evidence and truth classes, while `PUBLIC_ENDPOINTS` separately
hard-codes executable regional URLs. A source can therefore be researched in YAML but absent from
execution, or executable with metadata that disagrees with YAML.

Resolution: retain YAML as the source of truth and register only adapter names in code. Validate at
startup that every executable source has exactly one registry entry, admissibility record and
adapter.

### Stale and manually assembled reports

`reports/regional-data-quality.json` states zero downloaded bytes and `blocked_before_ingestion`,
whereas `regional-source-execution.json` records the completed 38.7 MB capture. Some reports are
written by CLI code, some by `regional_reports.py`, and some are static audit artifacts.

Resolution: generate a timestamped `run-summary-v2.json` from manifests, quality reports,
admission decisions and model outputs. Generate current Markdown and compact committed release JSON
from that summary. Historical reports remain immutable and carry an explicit `superseded_by` field
or are placed under `reports/history/`; they must not silently conflict with current status.

### ENTSO-E adapter boundary

The current ENTSO-E downloader supports A65/A75 and hard-codes process type A16 plus the
Germany-Luxembourg domain. It is not an A63 redispatch or A78 outage adapter. Its parser also does
not expose document `mRID`, `revisionNumber`, `createdDateTime`, document status or asset identity.

Resolution: retain the working A65/A75 adapter and introduce `entsoe_events.py` with explicit
request contracts for each document type. First run a bounded revision-recovery experiment; do not
admit ENTSO-E event data until it proves whether older revisions are recoverable.

## OneDrive-first storage policy

The dedicated data root remains authoritative for all durable artifacts:

- `raw/blobs`: immutable content-addressed source payloads;
- `manifests/captures`: every retrieval attempt and blob reference;
- `normalized/<schema>/<source>/<version>`: normalized records partitioned by source and period;
- `quality/<source>/<profile-version>`: field, timestamp, unit, duplicate, revision and missingness
  profiles;
- `quarantine`: invalid schemas, ambiguous identities and non-admitted datasets;
- `features/<dataset-version>` and `targets/<dataset-version>`: frozen leakage-safe model tables;
- `models`, `predictions` and `simulations`: versioned outputs with input hashes;
- `exports` and `backups`: portable artifacts only.

The local work root is limited to resumable download parts, parsing scratch space, caches, active
model runs and live Neo4j data. Completed artifacts move atomically to OneDrive, are read back and
hash-verified, and then local staging is removed.

OneDrive is a synchronized filesystem, so a file can still consume local disk while synchronized.
After verification and confirmed cloud synchronization, Windows Files On-Demand may be used to
free local copies. The ingestion code must not automatically dehydrate files because sync state and
offline requirements are user-controlled. It should report file size and OneDrive availability
attributes so cleanup can be performed deliberately.

## Phased implementation

### Phase 0 — Unify storage without changing scientific results

1. Add `SnapshotStore` and `SnapshotManifestV2` to the storage layer.
2. Add content-addressed blob reuse and separate retrieval manifests.
3. Route generic, regional, DWD and ENTSO-E writers through it.
4. Change `live_backtest.py` and `regional_reports.py` to use resolved storage.
5. Add a read-only legacy inventory and migration command.
6. Copy and verify legacy repository data into the dedicated OneDrive store without deleting the
   originals.
7. Add a catalog mapping source, request period and capture time to a blob hash.

Gate: identical inputs produce identical reports before and after migration; every durable artifact
is in the dedicated OneDrive tree; duplicate captures reuse a blob; all hashes verify.

### Phase 1 — 50Hertz historical sample adapter

1. Add a typed request for one publication date, initially using the date-addressable official
   page.
2. Preserve raw HTML and, if an official CSV endpoint is discovered, preserve CSV separately.
3. Parse interval start/end, increase/decrease MW, generation/publication time, record ID and
   revision.
4. Normalize to the existing `GridEvent`; unknown values remain null.
5. Detect page templates, error pages, selected-date mismatches and schema changes.
6. Test normal, revised, apparently empty, DST and year-boundary fixtures.

Gate: representative fixtures round-trip to canonical events; revision selection at historical
issue times passes; empty, missing and failed responses remain distinct.

### Phase 2 — Pilot and complete coverage audit

1. Capture a stratified pilot: one ordinary month and one high-revision month per year from late
   2021 onward, plus both DST transition weeks.
2. Produce daily availability states: `valid_with_records`, `valid_empty`, `failed`,
   `schema_changed`, `date_mismatch` and `not_published`.
3. Profile revision-chain gaps, publication latency, interval completeness, duplicate IDs, MW
   directions and units.
4. Store the coverage matrix and its manifest in OneDrive.
5. Only after this gate passes, crawl the remaining dates with checkpoint/resume and conservative
   rate limiting.

Gate: missing days are classified without treating absence as zero; publication-time reconstruction
is demonstrated on multiple revised intervals; reuse terms are documented.

### Phase 3 — 50Hertz asset outage adapter

1. Capture the outage register and authoritative downloadable archives.
2. Normalize revision ID, asset name, voltage, category, start/end and last modified.
3. Preserve the distinction between last modified and first publication.
4. Add deterministic asset normalization and quarantine collisions.
5. Retain transmission-asset resolution; never map an outage to a distribution node by proximity.

Gate: revision observations are retained, ambiguous assets enter manual review and missing archives
do not become no-outage labels.

### Phase 4 — ENTSO-E revision experiment

1. Add A63 and A78 request/response fixtures and parsers.
2. Query small known periods and compare normal period extraction, document-ID retrieval and file
   library results where available.
3. Record `mRID`, revision, creation time, status, business type, domain and affected asset fields.
4. Determine empirically whether superseded versions remain retrievable.
5. Review ENTSO-E reuse terms for stored and derived outputs.

Gate: either admit publication-aware revisions or explicitly restrict ENTSO-E to latest-state
context/cross-validation. A revision number in the latest document alone is not sufficient.

### Phase 5 — E.DIS and regional context

1. Keep completed E.DIS measures as retrospective target candidates.
2. Continue searching for a defensible first-publication timestamp and historical revision log.
3. Encode Berlin and Bremen local-time ambiguity explicitly; use them only after annual publication
   and DST semantics pass.
4. Keep DWD and Germany-Luxembourg load/generation as contextual features.
5. Preserve separate feature names for national, control-area, operator-area and regional values.

Gate: no source is silently promoted across geographic resolution; E.DIS is not used as a
forecast-time feature until publication semantics are proven.

### Phase 6 — Identity and hourly dataset

1. Extend the operator identity configuration with versioned asset aliases and authoritative area
   evidence.
2. Add collision detection, confidence, match method and manual-review output.
3. Build hourly features only from revisions published by the issue time.
4. Add source-availability and revision-completeness intervals.
5. Build targets at the actual published resolution for 1, 6, 24 and 48-hour horizons.
6. Freeze features and targets with full input hashes in OneDrive.

Gate: deliberate future revisions and later retrievals cannot change an earlier feature row;
unknown source periods yield null targets or abstention, never zero.

### Phase 7 — Out-of-sample control-area modelling

1. Run historical-rate and seasonal baselines.
2. Add logistic regression and a small regularized tree baseline.
3. Fit Platt and isotonic calibration only on prior periods.
4. Evaluate complete years where coverage permits, plus season, lead time and missing-source
   partitions.
5. Compare PR-AUC, precision, recall, false-negative rate, Brier score and calibration error.
6. Keep the configured gate failed when yearly precision is unstable or coverage is insufficient.

Output label: `50Hertz control-area published constraint-event risk`. It is not Berlin nodal risk
or available connection MW.

### Phase 8 — Reporting, monitoring and operator boundary

1. Generate the four output layers independently.
2. Add a versioned source/admission table and unknowns ledger to every release report.
3. Monitor the Stromnetz Berlin publication page by immutable snapshots and change detection;
   monitoring does not turn illustrative capacity examples into measurements.
4. Send the existing minimum operator-data request after user approval of recipients and channel.
5. Keep operator responses under a separate confidential root with access controls; do not place
   them in the public research-data tree or Git.

Gate: operator-confirmed capacity remains unavailable until a traceable operator response supports
the exact connection point, time, conditions and MW value.

## Required new tests

- Content-addressed deduplication with multiple retrieval manifests.
- Interrupted-download cleanup and retry/backoff behavior.
- Legacy-to-OneDrive migration verification and idempotency.
- No hard-coded repository-data reads when cloud storage is configured.
- 50Hertz selected-date mismatch, HTML schema change and valid-empty fixtures.
- Revision ordering by publication time, including same-time ambiguity quarantine.
- CET/CEST spring gap and autumn fold tests.
- Outage cancellation and last-modified revision tests.
- ENTSO-E A63/A78 acknowledgement, pagination/period bounds, revision and status tests.
- Asset-name collision and regional-only identity tests.
- Missing-source target abstention and publication-revision leakage tests.
- Deterministic feature, model and report hashes across repeated runs.
- Secret scanning that checks manifests, errors and command output fixtures.

## Commit sequence

1. `Unify OneDrive snapshot storage and migration inventory`
2. `Add publication-aware 50Hertz historical pilot adapter`
3. `Audit 50Hertz coverage and ingest transmission outages`
4. `Probe ENTSO-E event revision recovery`
5. `Build leakage-safe 50Hertz constraint dataset`
6. `Add rolling calibrated regional constraint baselines`
7. `Reconcile reports and document release decision`

Each commit must keep tests and lint passing, contain no raw data, and be pushed normally without
rewriting history.

## Decisions that remain deliberately unavailable

- Berlin, Brandenburg, Bremen or Frankfurt nodal loading;
- available connection MW;
- operator connection feasibility;
- equipment ratings and topology;
- queue and reservation state;
- historical operator connection outcomes.

These require operator evidence and cannot be inferred from the proposed public-data pipeline.
