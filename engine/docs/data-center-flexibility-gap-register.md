# Data-center flexibility gap register

Baseline: 2026-08-31. Existing dirty-tree files are user-owned and were not discarded.

| ID | Gap / overlap | Canonical resolution | State |
|---|---|---|---|
| G01 | `run_capacity_study` directly orchestrated AC work beside `StudyPipeline` | Versioned ensemble workflow now invokes existing owners through `StudyPipeline`; runner is an application/persistence adapter | Implemented |
| G02 | Aggregate `phase2.thermal_workload` had no jobs, GPUs, deadlines or SLA model | Deterministic job/SLA/action/facility package plus energy-reconciling adapter to the aggregate owner | Implemented |
| G03 | `optimized_deflex` uses SciPy/HiGHS but lacks facility/job contracts | Reuse formulation under one facility optimizer; do not create uncertainty framework | Open |
| G04 | Phase 2 and 3 are mostly isolated | Add reference-based end-to-end result and pipeline stages | Open |
| G05 | ENTSO-E/DWD and researched German sources lack one observation contract | Wrap existing captures with provider-neutral market-data adapters | Open |
| G06 | No FlexMeasures/DCGM/Kubernetes/Slurm/OpenEMS production adapters | Optional, replaceable, read-only or inert adapters | Open |
| G07 | Phase 3 could be misread as operational authorization | All integrated outputs must retain `automatic_live_dispatch_authorized: false` | Guardrail |
| G08 | OneDrive `telemetry` name does not distinguish exports from live data | Split configuration and reject live database paths in OneDrive | Open |
| G09 | `hourly_ac`, `flex_study`, `synthetic_operator`, and synthetic grid modules overlap production concepts | Keep non-authoritative; imports from canonical packages are prohibited | Guardrail |
| G10 | No structured capacity-to-flexibility handoff | Versioned per-PCC requirement references the exact result and provenance and is emitted in canonical artifacts | Implemented |
| G11 | Realizations for multiple PCCs could enter one aggregate | Realizations retain `pcc_id`; aggregation and results are isolated per PCC | Implemented |

No production module currently imports a registered non-authoritative demonstration as its calculation authority. Existing truth-class and claim restrictions are unchanged.
