# Regional Constraint Evidence V1 execution

## Outcome

The public-source capture and validation pipeline is operational, with Microsoft OneDrive as the
durable system of record. Real 50Hertz, E.DIS and German-TSO data were captured and profiled.
No source yet passes every historical publication, revision, identity and reuse gate, so the real
regional model remains unavailable. This is a fail-closed result, not evidence of zero congestion.

Berlin or Brandenburg nodal loading, connection headroom and available connection MW remain
unknown. Operator-confirmed capacity remains unavailable.

## Cloud storage

- Provider: Microsoft OneDrive filesystem synchronization
- Durable root: `C:\Users\sinak\OneDrive\GridPulse Capacity Research Data`
- Disposable work root: `C:\Users\sinak\Documents\GridPulse-Capacity-Work`
- Raw files after capture: 36 files, 38,749,302 bytes
- Normalized data: one JSONL file, 215,738 bytes
- Quality reports: eight files, 11,844 bytes
- Verified immutable manifests: 18; failures: 0

Downloads use local staging only while incomplete. Completed content is hashed, copied atomically
to OneDrive, read back for SHA-256 verification and removed from staging. Credentials are never
written to manifests. Live Neo4j data remains outside the synchronized directory.

## Real source findings

### 50Hertz measures RSS

- 348 published revisions for 192 unique 15-minute intervals
- Coverage: 2026-08-14 22:00 UTC through 2026-08-16 22:00 UTC
- 43 intervals had more than one published revision
- Maximum observed revision: 9
- 43 final intervals had non-zero increase or reduction MW
- Revision numbering was contiguous in the captured window
- Publication timestamps include explicit offsets and are preserved in UTC
- Increase and reduction remain separate; they are not silently netted

The feed is admitted for prospectively captured 50Hertz control-area context. It is not admitted
for rolling historical model training because the live window is short, historical archive
completeness is unproven and an open redistribution licence was not confirmed.

### E.DIS completed measures RSS

- 50 records
- Stable GUID and operation identifiers were present
- Area, constraint location and installation keys were populated in all captured records
- No exact duplicates occurred in the snapshot
- MW/MWh fields were not established by this feed

The RSS `pubDate` has not been proven to be the event's original publication time. The source is
therefore quarantined from targets and training. Missing rows must not be interpreted as zero.

### Netztransparenz redispatch archive

- 40,118 records
- Coverage: 2 April 2013 through 31 December 2020
- All timestamps declare UTC
- Average MW, maximum MW and MWh fields passed numeric parsing
- 568 exact duplicate rows require source-specific resolution; totals must not be summed blindly
- The archive has no source record ID, publication timestamp or revision number
- The archive lacks the `NETZREGION` field documented for the current API format

The archive is authoritative historical outcome context but cannot reconstruct what was known at
an old prediction issue time. It is not admitted for publication-aware training.

### Other captured publications

Immutable HTML snapshots were retained for 50Hertz outage planning, Stromnetz Berlin load and
network publications, wesernetz Bremen/Bremerhaven load publications and NRM Frankfurt network
publications. These establish publisher context and discoverable downloads, not named-equipment
loading or available MW. Exact downloadable load files require individual file endpoints and
source-specific profile approval before feature admission.

### Regional load files

- Stromnetz Berlin aggregate history contains 454,989 quarter-hour points.
- Stromnetz Berlin high-voltage history contains 210,432 quarter-hour points for 2020–2025.
- The Berlin high-voltage values are explicitly declared in kW; 2025 ranges from 790,469 to
  1,995,320 kW.
- wesernetz Bremen and Bremerhaven each contain 35,040 quarter-hour points for 2025.
- Bremen ranges from 204.970 to 738.974 MW with no negative or invalid numeric rows.
- Four duplicated local timestamps occur at the autumn clock change, but the files do not publish
  UTC offsets or an explicit fold field.

These load files are real regional/operator-published measurements. They remain quarantined from
leakage-safe features until timezone/DST and annual publication semantics are encoded and tested.

## Geographic resolution achieved

- 50Hertz: TSO control area only
- E.DIS: operator service-area and published constraint-location context
- German TSO archive: requesting/instructing TSO and affected-installation text
- Berlin, Bremen and Frankfurt pages: region, operator area or voltage-level context

No nearest-node assignment is treated as official. Unmatched or ambiguous operator and asset
identities remain in manual review. Public assets are not assumed to be distribution substations.

## Model and calibration decision

No real regional classifier was fitted. Consequently, yearly precision, recall, PR-AUC, Brier
score and calibration results are unavailable. Publishing fixture-derived or short-window scores
would be misleading. The configured release gate remains failed because it requires an admitted
source, a complete publication archive and at least three yearly holdouts.

## Synthetic and flexibility boundary

The existing benchmark continues to cover ten structurally selected candidates, four synthetic
network families, four operating scenarios and paired N-0/N-1 studies. The DeFlex-style study
contains 800 deterministic annual summaries for 10, 25, 50, 100 and 200 MW site scenarios. Both
synthetic release gates remain failed and Berlin live capacity remains unknown.

The completed rerun evaluated 320 N-0/N-1 cases and covered 15 unique candidates across the
family samples. Observed safety metrics were: 53.869 MW mean absolute error, 45.0 MW median
absolute error, 19.06% overstatement, 11.87% severe overstatement, 87.5% interval coverage,
35.0% top-10 recall and 18.75% contingency-selector recall on 32 exhaustive audit cases. These
results correctly fail both the ranking and capacity-band gates.

## Operator data still required

- anonymized network connectivity and switching states
- normal and emergency equipment ratings
- hourly or quarter-hourly equipment loading
- planned and unplanned outage history
- contracted, queued and reserved demand
- applicable N-1 and protection policies
- historical connection requests, assessed points and outcomes
- firm or conditional MW offered and reinforcement requirements

Only operator-confirmed evidence may support confirmed available connection capacity.

## Verification

- Unit tests: 87 passed in the final run
- Focused new ingestion/storage/identity/load tests: passed
- Ruff lint across `src` and `tests`: passed
- Ruff format check: 26 pre-existing files remain unformatted; the new and intentionally changed
  files are formatted, and unrelated mechanical formatting changes were removed from the diff
- Cloud storage write/read verification: passed
- Regional manifest verification: 18 checked, zero failures
- Secret-pattern scan: no credentials found
- Full synthetic AC N-0/N-1 benchmark: completed
- DeFlex annual dispatch summaries: 800 completed
- Type checker: not configured in `pyproject.toml`
- Real rolling regional backtest: not run because no event source passes the admission gate
