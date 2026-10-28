# Canonical optimisation integration — qualification checkpoint

Date: 2026-10-23. Code and qualification only; runtime approval is outstanding.

## Implemented in this candidate (remote qualification recorded below)

- The single application parser passes battery, onsite generation, fatigue and fleet capacity
  to the existing optimiser instead of silently dropping them. Unknown top-level fields and
  duplicate profiles are rejected. Manual, uncertainty and rolling entry points share it.
- Battery model and replay share asymmetric charging capability, health-adjusted maximum
  SOC, protected backup energy and explicit interval duration. Initial-interval self-discharge
  is included in both paths. Result exposes per-resource replay trajectories for SOC charts.
- Fleet GPU capacity is enforced by the MILP and checked independently during replay.
- Workloads are conservatively limited to a single uninterrupted run. This is **not** yet
  checkpoint/restart optimisation or stateful running-job scheduling.
- Feasible timeout incumbents are no longer excluded merely because optimality was not proved.
- Subhourly fatigue measures elapsed hours and MWh rather than treating samples as hours.
- Battery ramp and explicit inverter-mode dwell share initial operating state with replay.
- Job maximum start delay, initially-running state and remaining work are enforced. Free
  `delay_start` pauses after execution has begun are rejected; uninterrupted scheduling remains
  a conservative subset, not full checkpoint optimisation.
- Existing HTTP transport now preserves canonical assets; a real in-memory HTTP/job-runner/MILP
  integration test runs against a pinned candidate in the application repository. No database
  or live customer integration is needed by this test.
- Engine version comes from package metadata. A single replay-based acceptance function is
  shared by fallback and uncertainty. Baseline fallback is explicitly not physically certified.
- Transport schema is published in the existing manifest and tested against API field inventory.
- Result includes the engine-calculated baseline and explicit planning intervals; the staged
  frontend projection validates contiguous timestamps as well as array identities.
- Remote-only CI runs fast transport/solver gates before planning regressions, with one
  numerical thread and a 20-minute job bound. No local tests, builds or solvers are permitted
  on this workstation for this release.

## Remote qualification

Initial run 39947357395 failed before test collection: the Actions token in this private repository
cannot clone the other private repository, SinaDevCool/gridpulse. Configure
`GRIDPULSE_CORE_READ_TOKEN` in this repository with Contents:read on gridpulse only.
The user configured the secret and private checkout succeeded on run 39947912392, attempt 2.
Its 28 fast tests passed, but the broad command selected no tests (exit 5). The command was
fixed rather than suppressing exit status. Run 39949480950 at commit 760e7dc passed both
gates: 28 fast tests; 297 full-suite tests passed, 26 skipped (25.40 seconds).
Additional joint transport, generation-effect, asymmetric charging and shared-fleet tests
were then added; their candidate must pass before further qualification is claimed.
The workflow checks out the exact pinned core commit using that secret; credentials
are not persisted. Do not copy core/solver source to bypass the boundary, weaken tests, or
fall back to local heavy validation. No production deployment or main merge is authorised.

## Remaining six-workstream acceptance gates

1. Input mappings: cover every left-panel field with explicit hard constraint, initial state,
   objective, assumption or metadata classification; reconcile PUE/component accounting.
   The user selected component accounting first. A readiness-gated adapter now maps battery,
   facility target, fleet and delay settings, retains reviewed job profiles and terminal policy,
   and labels PUE as reference. Matching reviewed GPU calibration is mandatory; no automatic
   profile invention is authorised. Do not silently apply aggregate PUE as well.
   Aggregate shiftability must not
   grant permission to pause individual jobs. Add versioned bounds and model-size limits.
2. Electrical model: qualify timestamp-based availability, separate evidenced equipment limits
   and broader multi-battery cases. Ramp/dwell and subhourly fatigue now have regression tests.
3. Jobs: complete checkpoint/restart optimisation, interruption
   permissions, broader SLA limits, GPU compatibility/idle draw. Current uninterrupted
   subset must remain explicitly labelled; replay alone is not an optimisation formulation.
4. Uncertainty: existing independent scenario solves remain a perfect-information benchmark,
   NOT a common nonanticipative plan or genuine DRO/CVaR optimisation. Build common decisions
   and recourse, then correlated stress and holdout tests. Do not activate these claims.
5. Rolling: existing chronological wrapper is NOT physical-state MPC. Implement observation
   cutoff proof, SOC/job/thermal state carryover, committed near-term actions and revalidated
   fallback before operational use. Carrying a fingerprint is insufficient.
6. Integration: frontend staging projection validates replay success, request fingerprint,
   identities and a common horizon for three tab projections. It is deliberately not selected
   by the live store. Full UI/store integration, shadow qualification, negative-price exact
   meter accounting and hierarchical objectives remain outstanding. Live heuristic stays active.

## Execution qualification update

The existing application job runner now owns an isolated, task-owned solver child process.
Cancellation or lease loss terminates that child before publication; a 630-second wall-clock
budget and 32 MB result envelope are explicit. Persistence checkpoints are bounded to once
per second. This is code staged in PR #62, not a provisioned worker or a production activation.
The private-engine workflow pins the exact application candidate and runs the real HTTP
integration against this execution path. Container memory sizing remains an approval gate.

## Release boundary

No Supabase changes; no paid runtime provision; no deployment of this private engine;
no PR #37 changes. Retain the live heuristic until qualified integration and runtime approval.
Never call this candidate fully implemented, qualified, production-ready or German-regulation
certified. Future deployment needs an approved artifact/runtime and evidence-backed site rules;
annual reporting and market prequalification are separate from dispatch feasibility.
