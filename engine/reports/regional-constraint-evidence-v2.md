# Regional Constraint Evidence V2

Generated 2026-08-16. This report describes a research backtest. It does not
establish nodal loading, grid headroom, connection feasibility, or available
connection capacity in Berlin, Brandenburg, Bremen, or Rhine-Main.

## Outcome

The milestone produced a publication-aware, hourly 50Hertz-control-area event
dataset and experimental rolling-origin constraint-risk models. It did not
produce a Berlin or Brandenburg node model. All model release gates remain
failed because complete publisher-side revision retention, deletion semantics,
reuse rights, and operator validation are unresolved. Operator-confirmed
available capacity remains unavailable and `available_capacity_mw` remains
null.

## Repository and storage audit

- Work was confined to the separate `GridPulse-Fullb` research repository.
- Durable data is stored under
  `C:\Users\sinak\OneDrive\GridPulse Capacity Research Data`.
- Temporary work is configured under
  `C:\Users\sinak\Documents\GridPulse-Capacity-Work`.
- The OneDrive store contains 1,937,424,364 raw bytes, 580,613,488 normalized
  bytes, 74,840,914 feature bytes, 357,273 model bytes, and 86,438,209
  prediction bytes. Manifests and quality reports are stored separately.
- Raw payloads use content-addressed SHA-256 blobs. Retrieval observations are
  independent immutable manifests, so identical payloads are not duplicated.
- Ninety legacy repository-local payloads (433,136,224 logical bytes) were
  migrated without deleting their originals. Eighteen older cloud snapshots
  were compacted after hash verification, removing 38,749,302 redundant bytes;
  their content remains recoverable through replacement manifests and blobs.

The audit found split storage readers, duplicate payloads, multiple manifest
formats, stale generated reports, disconnected source registrations, and a
two-candidate synthetic execution path. The storage readers now share one
catalog, generated reports were not accidentally overwritten, the event
adapters feed one canonical contract, and the synthetic benchmark retains the
expanded all-eligible-candidate execution from the preceding milestone.

Repository changes in this milestone are deliberately narrow:

- `config/source_admissibility.yaml`: executed-source decisions and limitations.
- `src/capacity_backtest/constraint_dataset.py`: horizon-neutral target contract.
- `src/capacity_backtest/constraint_model.py`: rolling models and calibration.
- `src/capacity_backtest/storage.py`: verified legacy-cloud compaction.
- `src/capacity_backtest/cli.py`: model and storage-compaction commands.
- `tests/test_constraint_model.py` and `tests/test_storage.py`: deterministic
  helper and destructive-boundary coverage.
- `reports/regional-constraint-evidence-v2.md`: this consolidated result.

## Sources executed and admissibility

### 50Hertz congestion-management measures

- Official CSV endpoint: public, no authentication, UTC quarter-hours.
- Coverage: 171,160 unique quarter-hours from 2021-09-28 through 2026-08-16.
- Duplicate intervals: zero. Maximum final revision: 31. Intervals whose final
  revision exceeds one: 37,612.
- The CSV exposes the effective/latest revision. Date-addressable HTML pages
  expose numbered revision chains and publication generation times.
- All 1,023 local dates implied by revised CSV intervals were captured; the
  store contains 1,049 daily quality records including pilot/overlap dates.
- Increase and reduction MW are preserved separately. They are not implicitly
  netted. Unknown MW remains null.
- Geographic resolution is the 50Hertz control area, not a DSO node.
- Experimental analysis is allowed; training admission and operational release
  are false because publisher immutability, deletion completeness, and an open
  reuse licence are not confirmed.

### 50Hertz transmission outages

- Public rolling RSS captured 100 published versions representing 85 unique
  events; 39 events had multiple observed versions and all 100 versions named
  assets.
- The feed does not constitute a complete historical archive. Percent affected
  is not converted to MW because equipment ratings are unknown.
- Admitted only for prospective operator-published outage context and identity
  review, not historical training or capacity inference.

### ENTSO-E Transparency Platform

- The existing API token was detected and successfully exercised without being
  written to logs or artifacts.
- A bounded A78 unavailability probe for 2026-08-15 through 2026-08-16 returned
  464 effective documents over three offset pages. The largest returned
  revision number was 320.
- `revisionNumber` was rejected as an input parameter and an mRID query returned
  the effective/latest document, so superseded-version reconstruction was not
  established.
- An authenticated A63 redispatch probe returned an explicit API error that the
  requested document-type combination was invalid or unavailable.
- A78 is retained for latest/effective cross-validation and prospective
  snapshots only. Neither probe is admitted to historical training.

### Other researched/registered sources

- SMARD/Bundesnetzagentur redispatch and national series remain useful at their
  published aggregation, but do not supply historical nodal truth or proven
  as-known revision reconstruction for this milestone.
- E.DIS completed measures remain retrospective labels until publication-time
  history and stable identity are proven.
- Stromnetz Berlin publications remain public context. They do not provide
  historical nodal loading, queue/reservation state, or confirmed headroom.
- wesernetz and Rhine-Main operator/public load publications remain contextual
  features at their actual resolution.
- No rejected or quarantined source was silently treated as a zero-event series.

## Canonical events and identity

The canonical record preserves source and source-record identifiers, event and
revision identifiers, retrieval/publication/start/end timestamps, operator,
control area, region, assets/geography, event type and direction, MW/MWh,
reason/status, geographic resolution, match method/confidence, truth class,
source URL, snapshot hash, and validation warnings. Every observed revision is
retained. Ambiguous DST publication times and uncertain identities are
quarantined or flagged. Retrieval time is never silently substituted for an
unknown publication time.

No nearest-node rule is used as official identity. The achieved identity level
is 50Hertz control area plus explicitly named transmission assets where
published. Berlin and Brandenburg remain regional-only when no authoritative
node attribution exists.

## Hourly datasets

| Horizon | Rows | Positive targets | Missing-feature rows | Coverage end (UTC) |
| ---: | ---: | ---: | ---: | --- |
| 1 h | 42,576 | 10,307 | 8,615 | 2026-08-15 23:00 |
| 6 h | 42,571 | 15,148 | 8,614 | 2026-08-15 18:00 |
| 24 h | 42,553 | 25,738 | 8,613 | 2026-08-15 00:00 |
| 48 h | 42,529 | 31,849 | 8,610 | 2026-08-14 00:00 |

Coverage begins at 2021-10-07 00:00 UTC. Targets are based on nonzero published
50Hertz redispatch records, not national-load percentiles. Features use only
revisions published by issue time and include publication-aware 1/24/168-hour
MW and active-interval lags plus calendar fields and availability flags.
Unavailable historical features are null/flagged, never replaced by zero.

## Rolling out-of-sample models

Models include historical event rate, seasonal/calendar rate, logistic
regression, and a regularized histogram-gradient tree. Logistic and tree
outputs are calibrated separately with prior-period sigmoid (Platt) and
isotonic calibration. Each reported test year is held out chronologically;
calibration is fitted only on the last 20% of the preceding period. 2026 is a
partial-year holdout.

The table below reports sigmoid-calibrated logistic regression. Accuracy is not
used as the primary metric.

| Horizon | Year | Precision | Recall | PR-AUC | Brier | Calibration error |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 h | 2022 | .920 | .882 | .933 | .040 | .011 |
| 1 h | 2023 | .917 | .865 | .939 | .060 | .023 |
| 1 h | 2024 | .911 | .863 | .931 | .057 | .016 |
| 1 h | 2025 | .902 | .828 | .921 | .076 | .019 |
| 1 h | 2026* | .902 | .816 | .926 | .072 | .018 |
| 6 h | 2022 | .875 | .698 | .864 | .102 | .059 |
| 6 h | 2023 | .934 | .699 | .905 | .114 | .028 |
| 6 h | 2024 | .906 | .677 | .894 | .116 | .023 |
| 6 h | 2025 | .911 | .662 | .910 | .128 | .041 |
| 6 h | 2026* | .879 | .732 | .914 | .117 | .080 |
| 24 h | 2022 | .561 | .839 | .793 | .232 | .187 |
| 24 h | 2023 | .898 | .536 | .880 | .186 | .082 |
| 24 h | 2024 | .760 | .699 | .868 | .186 | .054 |
| 24 h | 2025 | .804 | .838 | .912 | .164 | .067 |
| 24 h | 2026* | .780 | 1.000 | .902 | .156 | .015 |
| 48 h | 2022 | .621 | .992 | .831 | .221 | .134 |
| 48 h | 2023 | .854 | .812 | .919 | .165 | .094 |
| 48 h | 2024 | .810 | .952 | .914 | .153 | .047 |
| 48 h | 2025 | .876 | .995 | .947 | .113 | .075 |
| 48 h | 2026* | .883 | 1.000 | .935 | .102 | .026 |

One-hour yearly precision range is .019; six-hour range is .059; 24-hour range
is .337; 48-hour range is .261. Long-lead yearly precision is therefore
unstable. Strong short-lead metrics do not override the source-admissibility
failure or establish operational reliability.

## Release gates and unknowns

- Public constraint context: available at published control-area/asset level.
- Probabilistic regional risk: experimental 50Hertz-control-area artifacts
  available; release gate failed.
- Synthetic flexibility study: available only as a synthetic benchmark.
- Operator-confirmed capacity: unavailable.
- Confirmed available connection capacity: unknown.
- Berlin/Brandenburg nodal loading and headroom: unknown.
- Real switching topology, equipment ratings, protection policy, queues,
  reservations, and connection outcomes: unknown.

Operator validation still requires anonymized connectivity, normal/emergency
ratings, timestamped loading, topology/switching state, planned/unplanned
outages, contracted/queued demand, reserved capacity, N-1/protection policy,
and historical connection-study requests and outcomes. The existing operator
pilot package specifies essential/optional fields, anonymization, secure
handling, validation use, and non-publication commitments.

## Synthetic network and flexibility verification

The complete synthetic benchmark evaluated 320 cases, 15 unique non-slack
candidates, and four held-out network families. It retained 32 stratified
exhaustive-contingency audits. Mean absolute error was 53.869 MW, median
absolute error 45.0 MW, overstatement rate 19.1%, severe overstatement rate
11.9%, interval coverage 87.5%, top-10 recall 35.0%, and contingency-selector
recall 18.8%. Both the ranking and capacity-band release gates failed.

The deterministic flexibility study executed 10/25/50/100/200 MW site-load
scenarios across the synthetic candidates and operating scenarios. Its hourly
bounded dispatch reports constrained hours, consecutive interruptions,
curtailed/shifted energy, battery cycles, rebound, N-0/N-1 binding hours,
unsafe overstatement, and unserved energy. Several 200 MW cases were infeasible
or unsafe for most/all hours despite flexibility; the study therefore does not
support a generic flexibility uplift. Every result is classified
`synthetic_benchmark`; no synthetic envelope is a Berlin capacity estimate.

## Verification

- Unit and fixture tests: 99 passed.
- Ruff lint: passed.
- Focused Ruff formatting check: passed.
- Repository-wide formatting check: 24 pre-existing files would be reformatted;
  they were reported separately and not bulk rewritten in this milestone.
- Type checking: no repository type-check command is configured.
- Raw data, credentials, caches, virtual environments, and local cloud metadata
  are excluded from the commit.
- Full synthetic N-0/N-1 and flexibility benchmark: completed; both release
  gates failed as described above.
- Capture-manifest verification: 1,163 checked, zero failures.
- Deterministic model rerun: prediction SHA-256
  `3b5da5454a25f6b4b9f04f166e2042f7f7d06679925cdf25f74ded11eabb4c5b`
  before and after rerun.
- Credential-shaped assignment scan: no findings outside excluded fixtures.

Commit hashes and the pushed branch are recorded in the final delivery after
execution.
