# Quarter-hour synthetic planning qualification

Date: 25 October 2026. Candidate only; no deployment or database changes.

The application generates 96 contiguous 15-minute UTC intervals for the same
24-hour synthetic day. It reuses the existing facility-plan contract, job API,
SciPy/HiGHS optimiser, sparse constraints, physical replay and frontend projection.
The Python solver implementation and production runtime configuration are unchanged.
PUE remains reference-only under component accounting.

## Reproducible candidates

- Application source: dcfe384d99fd44b8339041675b0a16684f00dd7d.
- Engine qualification source: aaa2e9411f47f66ff17a2cfa6269626f60593645.
- Engine regression and genuine-result frontend round trip:
  https://github.com/SinaDevCool/GridPulse-Fullb/actions/runs/40159815792
- Free-sized container qualification:
  https://github.com/SinaDevCool/GridPulse-Fullb/actions/runs/40159817095

The existing workflows pin the exact application commit. They generate the browser
request rather than maintain a second Python copy. The real result is passed back
through the shared three-tab TypeScript acceptance test.

## Evidence

Normal CI: 43 focused Python checks, four frontend round-trip checks, and 329
regression checks passed. The regression stage explicitly skips 32 external/fixture
checks; browser-request checks run separately with their generated fixture.

The container passed 12 checks with a hard 512 MiB memory limit, no swap, 0.1 CPU,
bounded numerical threads, and the unchanged 30-second solver budget.

| Synthetic case | End-to-end seconds | Solver result | Relative gap |
| --- | ---: | --- | ---: |
| Default battery and workloads | 30.70 | Feasible, not proven optimal | 1.157% |
| Onsite generation | 30.60 | Feasible, not proven optimal | 1.319% |
| No battery, relaxed import target | 30.50 | Feasible, not proven optimal | 1.317% |
| Restricted flexibility, relaxed import target | 1.50 | Optimal within tolerance | 0% |

Process peak RSS was approximately 206 MiB in that container run; this is the test
process high-water mark, not a production memory guarantee. Container statistics,
inspection, logs and per-case JSON measurements are attached to the workflow.
The unchanged-target no-battery case correctly reports infeasibility and publishes
no accepted schedule.

Accounting regressions compare fixed hourly and quarter-hour schedules for battery
efficiency/energy, workload progress, energy tariffs and peak-power charges.
No exact action-for-action equality is required between independently optimised grids.

## Interpretation and release boundary

Feasible incumbents still require physical replay and truthful status/gap reporting.
Do not relabel them optimal, increase timeouts to hide a failure, or silently substitute
an hourly/heuristic result. This qualification covers synthetic cases, not arbitrary
customer facilities, cold-start latency or production uptime.

The earlier hourly launch qualification remains historical evidence. Existing hourly
results and marketing screenshots retain their original resolution/provenance.
Regenerate marketing captures from a genuine quarter-hour result when a release is
authorised. No production submission, runtime rollout, merge or marketing publication
is part of this change.
