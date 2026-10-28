# Physics-aware decision engine

## Ownership

GridPulse-Fullb owns the sole MILP, battery/workload/cooling simulators, replay, calibration, datasets and model artifacts. GridPulse-Full owns authenticated transport, job lifecycle, UI projections and provider-independent explanations. Serving never trains a model. No second optimiser, vector database, queue or Supabase schema is introduced by this work.

## Entry points

- `application.experiments.run_facility_experiment`: at most four sequential cases, four explicit changes per case, 96 intervals, five workloads and one battery; solver limit at most 30 seconds per solve. Wall-clock/cancellation is enforced by the product's existing isolated job runner.
- `alternative` reuses `run_facility_plan`. `frozen_plan` replays the accepted commands against changed conditions through existing physical simulators. These answer different questions and must not share an unqualified success label.
- `application.rolling.run_chronological_shadow`: chronological remaining-horizon solves carrying SOC, prior power/mode/dwell, workload remaining minutes and thermal debt. Cutoffs start at the original horizon boundary, increase strictly, and reject future forecast availability. No measured observations or control are implied.
- The existing probabilistic rolling benchmark remains available and is explicitly labelled as independent-window analysis, not validated common-plan control.

## Supported experiment inputs

| Change | Boundary |
| --- | --- |
| Battery energy | Rescale rated energy and submitted energy fractions; retain discharge MW |
| Battery power | Change discharge rating; retain independent charging rating |
| Initial SOC | Fraction of health-adjusted capacity |
| Import limit | Preserve operating reserve; retain the original connection requirement |
| Workload duration | One known job, multiplier 0.5–2, whole minutes |
| Availability | One non-running job, whole-minute earliest-start delay |
| Battery outage | One known interval and asset |
| Generation | Existing series times 0–2 |
| Cooling demand | Existing facility cooling load coefficient times 0.5–2 |

All other fields fail closed. Battery charge/discharge efficiencies, reserve, terminal energy, workload deadlines, GPU fleet and other existing restrictions continue through the canonical request and simulators. PUE remains a reference in component accounting.

## Result semantics

Every experiment retains input/result fingerprints, parent result identity, changes, mode, accepted/invalid status and read-only classification. Frozen replay returns import/target breaches, command shortfalls, completion/SLA/thermal/fatigue/requirement failures, first located violation and unsupported checks. No scenario probability, capacity offer, causal binding-constraint attribution or actual delivery is inferred. Work extending outside the accepted execution mask is explicitly rejected; the returned replay is not presented as an unchanged successful schedule.

Chronological replay rejects checkpoint/restart/migration boundary states not expressible in the current initial-state contract. Empty compute portfolios remain valid so battery, idle IT and cooling recovery can be solved through the remaining horizon. After the last event, the residual model has no active event reduction requirement; terminal and equipment constraints remain. Each revision records whether its remaining battery horizon was assessed. A failed solve stops subsequent revisions; no stale plan is substituted.

## Calibration and future datasets

DatasetManifest requires source/licence/cutoff, content hash, units/measurement boundary, transformation version and disjoint train/validation/test execution IDs. These metadata checks do not verify the source licence or create genuine measurements. Public benchmarks remain synthetic/reference evidence until site data independently validates them.

GPU held-out power prediction uses the training cap-to-measured-power curve, not the held-out target itself; throughput has its own error gate. Cooling's nonnegative coefficients and predictor are retained. Battery SOC MWh and AC power MW are gated separately; their absolute errors are never combined into one mixed-unit maximum.

Execution observations may declare `reference_work_duration_minutes`,
`configuration_id` and `power_boundary`. Throughput is reference work completed
per elapsed time, not merely a completion percentage. Real-data profile acceptance
requires the reference and configuration. Mixed configurations, reference work or
non-GPU boundaries cannot train one GPU profile. Legacy synthetic fixtures retain
their explicitly limited semantics; cap-based planning is unchanged.

Cooling calibration records topology and the observed IT/ambient range. Rank-
deficient training or held-out extrapolation blocks acceptance. `predict` refuses
out-of-range inputs. `replay_temperature_envelope` in the existing thermal module
is a separate, optional offline single-zone RC check. It requires explicit thermal
capacity (MWh thermal/K), conductance (MW thermal/K), cooling COP and temperature
bounds. It returns boundary temperatures and violations; carry its final state
between repeated events. No default site parameters, rack/coolant safety claim or
automatic change to the MILP follows from this reduced model. Qualify parameters
against measurements using the existing artifact/reviewer/release mechanism.

## Meter and dataset preparation

`adapters.component.aggregate_component_capture` reuses the sole strict component
parser and `observations.aggregate_observations`. Meter metadata declares power
samples versus interval averages versus cumulative energy, sample period, sign,
boundary and uncertainty. Power is held only across the explicit maximum gap;
counter deltas span adjacent observations. Overlapping averages, counter resets,
invalid samples, missing coverage and future-available revisions cannot silently
become a complete interval. Unknown interval energy/power is returned as `None`;
coverage, blockers and source IDs remain available. This is offline qualification,
not a live connection or public upload activation.

`chronological_dataset_manifest` wraps normalized captures with content hashes,
licence metadata, units, transformation version and chronological identity splits.
It rejects boundary-crossing executions instead of leaking them into two splits.
Source licensing and source-specific normalization still require review; declaring
metadata does not prove permission or site applicability. Existing DWD/ENTSO-E
capture stays the source path. ENTSO-E A44 parsing supports explicit EUR/MWh at
15/30/60-minute resolutions, including negative prices; the generic CSV price
adapter rejects nonfinite prices and equivalent duplicate instants.

Model artifacts contain parameters, operating range, dataset lineage, held-out thresholds, reviewer and approval time. JSON artifacts are content-addressed and integrity checked. CalibrationRegistry optionally persists append-only reviewed decisions/rollback with flush+fsync. This is a single-writer local research journal, not a concurrent production registry. No automatic promotion, training or measured calibration has taken place.

## Release qualification

Existing optimiser CI has a physics-aware focused gate before full regression. Python suite ownership remains in tests/conftest.py. Build a wheel using the existing packaging toolchain, freeze its exact dependency lock, then use scripts/seal-engine-release.py to hash the already-built wheel, exact source revision, lock and calibration identities. The command does not build/deploy or assert that tests passed. Publish only the candidate tested by CI; changing the source invalidates that qualification. The currently installed editable metadata may still report the previous release until packaging is updated.

## Validation and deployment boundary

Focused regressions cover replay breaches, baseline tampering, budgets, workload extension, temporal leakage, predictor errors, artifact tampering and persistent review decisions. Product cross-repository qualification exports the existing engine fixture and runs it through the real authenticated API/job runner. No production activation, Supabase migration, billing change or parked PR #37 work is part of this implementation.


## Operational-analysis hardening

Financial accounting now integrates each interval's own duration. `application.accounting.run_facility_accounting` prices only the frozen accepted schedule through the same energy integration primitive used by historical economic replay. It retains the owned parent result fingerprint and excludes full-bill items without supplied billing rules. No optimisation is run by this tool.

Observation alignment normalises aware timestamps, rejects duplicate axes, and validates finite values, component units, quality/missing consistency, hashes and completeness thresholds. These checks do not manufacture measurements or prove calibration.

GPU calibration records now retain the training-derived measured-power curve. `load_qualified_model` is an explicit artifact applicability gate: content integrity, release inclusion, held-out errors, approval time, measured provenance and every operating-range dimension must pass. A caller must verify the wheel/lock manifest before using it. No empirical model is automatically activated; no real site data has been supplied.


## Reviewed experiments and common-command analysis (2026-10-27)

The single engine remains the numerical owner. `application.experiments.comparison_metrics`
standardises replay energy, target duration, SOC, cycles, completion and rebound;
missing metrics stay null, not zero. Alternative acceptance requires solver status,
physical feasibility and no diagnostics. `data_center.plan_evidence` supplies observed
margins with source paths. These are not causal binding-constraint explanations or
MILP shadow prices.

`data_center.common_plan.optimize_common_plan` assembles scenario copies of the exact
canonical MILP through an internal solver seam. Equality constraints bind all physical
workload, checkpoint, battery and cooling commands across scenarios; electrical states
and import auxiliaries remain scenario-dependent. It solves one assumed-weight
objective, checks the entire incumbent including equality links, then passes every
scenario through the same canonical incumbent checks and physical replay. It is bounded
to four scenarios, 96 intervals, the existing combined variable budget and a 30-second
solve limit. No adaptive recourse or empirical reliability probability is claimed.
Per-scenario optimality gaps are intentionally absent: only joint optimality is meaningful.
`application.uncertainty` selects this with `evaluation_method=common_command_scenario_milp`;
the default independent benchmark is preserved and remains explicitly labelled.

Checkpointable workload inputs add an optional initial execution state, remaining
checkpoint/restart overhead and cumulative pause/movement counters. Replay emits these
boundary states; chronological shadow replanning carries them without free progress or
resetting pause permission. Geographic migration remains rejected. Shadow fatigue combines
executed prefixes with each candidate suffix against the first reference and stops if
cumulative checks fail; it does not authorise execution or infer annual history before
the submitted horizon.

Offline workload calibration is available as:

```powershell
python -m capacity_backtest.application.calibration capture.json metadata.json candidate-artifacts
```

Metadata names dataset/source/license/cutoff/train_end/validation_end/truth_class/workload_id.
The existing workload adapter requires per-execution `available_at` for this pipeline.
Existing chronological manifests and power-profile fitting are reused: validation and
held-out test evaluations each fit only the training executions. It stores a content-addressed
candidate, never activates a model. Measured customer datasets, reviewer approval, cooling
and battery site calibration and an exact packaged release remain external qualification
gates. No dataset has been fabricated or promoted in this change.


Validation: full local engine regression passed 381 tests with 32 explicitly skipped
(cross-repository fixture injection and opt-in slow studies). Subsequent cumulative
shadow-fatigue coverage and battery common-command regressions passed in focused runs.
Ruff passed for changed Python modules. The no-deployment qualification workflow pins
the product contract revision b2a955bcef63954bafd20e0a3a2f122bfb31c6db and includes the
new common-plan, checkpoint and calibration tests before full regression. Local tests
do not substitute for qualification of a future hosted wheel or real-site measurements.

The first remote cross-repository projection caught the newly added diagnostic envelope field. The pinned product revision now accepts its single shared strict schema and retains rejection tests for invented/causal/nonfinite evidence.
