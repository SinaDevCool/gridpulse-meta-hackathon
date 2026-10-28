# Synthetic Benchmark V5 execution record

## Boundary

This milestone is a **synthetic benchmark**. It does not measure regional network headroom or
establish connection feasibility. Confirmed available capacity remains unavailable. Confidential
operator topology, ratings, loading, switching, reservations, queues, outage history, protection
policy, and connection outcomes were not supplied.

## Duplication audit

`config/synthetic_component_ownership.yaml` freezes one authoritative implementation per
calculation. The new modules reuse the existing network families, pandapower provider, synthetic
operator tables, event contracts, storage resolver, truth classes, and output layers. No second
topology or capacity calculator was introduced.

## Executed results

- Queue evidence: 320 synthetic requests, 39 rolling-origin/leave-one-family-out folds. Rolling
  unsafe firm-prediction rates fell from 0.85/0.80/0.95 for the historical-rate baseline to
  0.10/0.00/0.075 for logistic regression and 0.15/0.025/0.075 for random forest. These are
  synthetic diagnostics, not operator accuracy. The release gate remains failed.
- Contingency selector: 64 exhaustive fixed-injection audits. V3 binding recall was 31.25%; V4 was
  100% overall and in the minimum family, with 51.21% mean contingency reduction. The synthetic
  selector gate passed.
- Representative hourly AC: all 48 seasonal/revised-outage cases converged. The annual-package
  approximate N-1 envelope overstated the solved selected-contingency result in 95.83% of cases;
  mean absolute error was 41.02 MW and maximum overstatement was 146.01 MW. The approximation
  gate failed and this proxy must not be used as a flexibility or connection-capacity boundary.
- Optimized DeFlex: 40 cases (eight families x five sizes), 168 hours each. The LP produced zero
  envelope-overstatement hours, 3,375.93 MWh shifted, 23,804.88 MWh critical unserved and
  46,829.59 MWh flexible unserved. Aggregate unserved energy was zero for 10/25/50 MW cases,
  6,112.44 MWh for 100 MW, and 64,522.04 MWh for 200 MW. Its operational release gate remains
  failed because every envelope and load is synthetic.

## OneDrive artifacts

Generated rows are excluded from Git and stored beneath
`C:\Users\sinak\OneDrive\GridPulse Capacity Research Data` in the `features`, `models`, `quality`,
and `simulations` trees. Queue features occupy 8,505 bytes, queue metrics 54,460 bytes, the
contingency audit 46,695 bytes, representative hourly AC artifacts 14,765 bytes, and optimized
DeFlex artifacts 1,504 bytes. Credentials, caches, and large generated tables are not committed.

## Operator path

The intake validator requires external confidential storage, explicit units/geography/use terms,
and SHA-256 verification. Reconciliation accepts only predictions frozen before decisions and
rejects nearest/proximity identity as evidence. Even reconciled historical outcomes are not live
operator confirmation. The decisive next step is the confidential pilot package specified in
`reports/operator-pilot-data-request.md`.

## Verification

- 121 tests passed, including chronology, revisions, missing inputs, operator intake,
  optimization, AC detail, queue features, and contingency fixtures.
- Repository-wide Ruff lint passed; all changed Python files pass Ruff formatting. A
  repository-wide format check still identifies 22 untouched pre-existing files and was not
  applied to avoid an unrelated formatting rewrite.
- Git whitespace validation passed and the broad credential/private-key scan found no match.
- OneDrive storage health and write verification passed; the six-table operator-package manifest
  verified 702,317 rows.
- Queue and optimized DeFlex artifacts reproduced byte-for-byte on a second run (SHA-256 hashes
  unchanged).
