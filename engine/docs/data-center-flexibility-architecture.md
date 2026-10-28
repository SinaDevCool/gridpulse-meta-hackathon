# Data-center flexibility architecture

Status: accepted implementation boundary (ADR-004), 2026-08-31.

## Decision

`capacity_backtest.pipeline.StudyPipeline` is the sole high-level, fail-closed orchestration owner. `capacity_study.runner.run_capacity_study` is an application and persistence service that invokes the versioned ensemble-capable pipeline. Existing AC, contingency, ensemble and aggregation calculations are preserved behind stage adapters, not rewritten. Every capacity result and flexibility requirement is isolated to one candidate PCC; operator selection remains explicit and unset for unconfirmed candidates.

The product is divided into four bounded systems: capacity screening, flexibility planning, a shadow operational digital twin, and replaceable external adapters. Capacity screening remains the only owner of electrical headroom. Planning may consume a frozen, versioned envelope but cannot enlarge it. The digital twin accepts simulated or replayed telemetry and inert simulation commands only. External adapters cannot change truth classes, authorize capacity, or dispatch equipment.

Operator confirmation remains mandatory for an available-capacity claim. Public, reconstructed and synthetic evidence remains screening or simulation evidence. No LLM or cloud planning component may issue or approve a real-time command. Edge authorization, operator authorization, and technical readiness are separate states.

## Ownership matrix

| Responsibility | Canonical owner | Boundary |
|---|---|---|
| Truth and capacity claims | `capacity_backtest.contracts` | Only operator-confirmed evidence can claim capacity |
| Evidence/provenance | `capacity_backtest.domain.evidence` | Immutable cutoff and fingerprints |
| Capacity contracts | `capacity_backtest.capacity_study.contracts`, `capacity_backtest.domain.results` | No report parsing |
| Orchestration | `capacity_backtest.pipeline` | Fail closed on missing physics verification |
| AC network calculation | `grid_data.network_study` | Electrical authority |
| Forecasts | `capacity_backtest.phase1.forecasting` | No parallel forecast framework |
| Flexibility requirement | `capacity_backtest.domain.flexibility_requirement` and its capacity-study builder | References exact envelope/provenance |
| Aggregate workload/cooling | `capacity_backtest.phase2.thermal_workload` | Physical backlog and thermal debt |
| Battery | `capacity_backtest.phase2.battery` | State and reserve |
| Credibility/dependable capacity | `capacity_backtest.phase2.credibility`, `phase2.capacity` | Verification feeds the existing score |
| Telemetry/commands/readiness/replay | `capacity_backtest.phase3` | Simulation/shadow only |
| Optimized aggregate dispatch | `capacity_backtest.optimized_deflex` | Preserved synthetic benchmark formulation |
| Durable research storage | `capacity_backtest.storage` | Live databases and secrets excluded |
| Job, SLA and action contracts | `capacity_backtest.data_center.contracts` | Deterministic planning contracts only |
| Empirical workload power curves | `capacity_backtest.data_center.power_profiles` | Piecewise-linear; extrapolation prohibited |
| Workload action simulation | `capacity_backtest.data_center.workloads` | No external scheduler commands |
| Portfolio and SLA evaluation | `capacity_backtest.data_center.portfolio` | Conserves normalized work |
| Facility power balance | `capacity_backtest.data_center.facility` | IT load is not PCC import |
| Job-to-aggregate mapping | `capacity_backtest.data_center.phase2_adapter` | Calls the existing thermal/backlog owner |
| Facility flexibility assessment | `capacity_backtest.data_center.assessment` | Evaluates supplied schedules; does not optimize |
| Facility flexibility optimization | `capacity_backtest.data_center.optimizer` | Single deterministic MILP owner; proposals require canonical replay |

## Allowed new modules

Dedicated job/facility planning contracts, one facility feasibility optimizer, provider-neutral market observations, read-only telemetry adapters, inert edge simulation, and report composition from canonical contracts are allowed. Each must be registered before use and must adapt existing owners.

## Prohibited reimplementation

No new electrical envelope, forecast, evidence, truth, storage, aggregate thermal/backlog, battery, credibility, telemetry, command lifecycle, fail-safe, delivery verification, or replay authority may be introduced. Demonstration modules listed in the ownership registry cannot become production dependencies.

## Phase 2 planning boundary

The job-level model is deterministic simulation. It can power-cap, resize, delay, checkpoint, resume, or move modeled work only inside an in-memory schedule. It cannot emit Kubernetes, Slurm, GPU, battery, cooling, or equipment commands. Battery state remains owned by `phase2.battery`; thermal debt and aggregate backlog remain owned by `phase2.thermal_workload`; phase/reactive checks remain owned by `phase2.phase_power`; credibility and dependable capacity remain owned by their existing Phase 2 modules. Every assessment retains `automatic_live_dispatch_authorized: false`.

## Phase 3 optimization boundary

`data_center.optimizer.optimize_facility_flexibility` is the only facility-level optimization owner. It uses SciPy's HiGHS MILP interface already present in the study dependency set. It selects empirical workload power-profile points, battery charge and discharge, and bounded cooling reduction and recovery. Critical workloads, deadlines, SOC reserve and terminal targets, thermal debt, facility import, and the frozen flexibility envelope are hard constraints. Prices affect the objective only.

An optimal mathematical solution is a proposal, not an accepted result. The proposal is replayed through `evaluate_portfolio`, `simulate_battery`, `build_facility_trajectory`, `map_portfolio_to_phase2`, phase-power validation, fatigue evaluation, and `assess_facility_flexibility`. Replay or fatigue failure yields `replay_failed`. A hard-model failure runs the same formulation with event shortfall slacks for diagnosis and remains `infeasible`; diagnostic slacks can never establish feasibility. Stable ordering, a deterministic tie-break coefficient, and an input fingerprint make bounded runs reproducible. The result cannot authorize live dispatch.

## Phases 4–11 integration boundary

Uncertainty is a deterministic scenario wrapper around the facility optimizer; it does not own a solver or a forecast model. Historical backtesting preserves planning cutoffs and delegates technical and economic calculations to separate owners. Market products are provider-neutral evidence-classified contracts whose eligibility consumes dependable modeled flexibility and whose settlement consumes verified delivery.

Rolling planning stores forecast fingerprints, advances immutable cutoffs, and retains the last accepted plan when a later window fails. Shadow operation reuses `phase3.telemetry`, `phase3.commands`, `phase3.delivery`, `phase3.failsafe`, and `phase3.simulation`; generated commands use the `shadow-only` authorization identifier and no transport exists. Delivery verification feeds the existing Phase 2 credibility and dependable-capacity owners.

The data-center enquiry package serializes canonical contracts rather than parsing reports. Read-only external adapters capture immutable raw payloads through `SnapshotStore` before strict normalization. Adapters perform transport and parsing only, reject schema drift, and expose no write or equipment-command capability. All Phase 4–11 outputs retain `capacity_claim: false` unless the originating capacity result is separately operator confirmed, and all new planning, backtest, market, shadow, reporting, and adapter results retain live dispatch as unauthorized.

## Calibrated planner and shadow-pilot boundary

Facility measurement points explicitly map modeled components to physical boundaries. Bitemporal observations preserve event, availability, ingestion, sequence, quality, and evidence identity; post-cutoff revisions cannot enter planning. Empirical workload profiles, cooling, battery, and facility calibration use held-out executions or periods and retain model fingerprints. The bounded planner sets workload and solve-time limits and returns a replayable baseline with conditional flexibility disabled whenever optimization is not accepted.

All DCIM, BMS, UPS, EMS, workload, price, and PCC adapters are read-only parsers behind immutable capture. A static adapter safety gate rejects command imports and write-like calls. Cross-channel telemetry gates cover clocks, jitter, missing/suspect values, and energy balance. Planned-versus-observed residuals use transparent uncertainty bands and feed the existing Phase 3 fail-safe state machine.

Delivery baselines must be selected before an event. Delivery evidence includes response, sustained duration, rebound, battery/thermal/workload recovery, SLA, and telemetry validity. Calibration changes require held-out improvement and named reviewer approval and remain rollback-capable. Shadow reports and security readiness never authorize live dispatch. Real facility observations, controlled events, continuous pilot duration, external review, and operator acceptance remain external evidence gates and are represented as requested or blocking rather than simulated as complete.
