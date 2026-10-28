# Phase 2 dependable conditional capacity

## Status

Phase 2 is implemented. It converts Phase 1 conditional capacity into a dependable envelope
backed by explicit resource states, delivery evidence, recovery obligations, fatigue limits,
and phase/reactive-power checks.

## Battery trajectories

`capacity_backtest.phase2.battery` models configurable initial and terminal SOC, minimum reserve,
SOC uncertainty, charge/discharge efficiency, self-discharge, degradation, temperature derating,
maintenance unavailability, power limits, energy limits, delivered energy, shortfall, and
equivalent full cycles. A full battery is not assumed. Terminal SOC failure is a release blocker.

## Cooling and workload recovery

`capacity_backtest.phase2.thermal_workload` represents cooling curtailment as thermal debt and
deferred compute as an age-tracked workload backlog. Recovery consumes future electrical
headroom, respects separate power limits, and reports rebound peaks, unfinished recovery, and
deadline violations. Incomplete recovery blocks dependable conditional capacity.

## Fatigue

`capacity_backtest.phase2.fatigue` enforces consecutive-event duration, rolling-day event hours,
rolling-week event count, cooldown periods, cumulative shifted energy, and battery-cycle limits.
The result distinguishes mathematical feasibility from sustainable operation.

## Resource credibility and non-delivery reserve

`capacity_backtest.phase2.credibility` uses verified, time-decayed delivery records. Per-resource
credibility includes delivery success, delivered/requested ratio, response-time success,
availability, a conservative Wilson lower bound, and a failure-correlation group. Declared MW is
therefore never summed directly. The difference between declared and dependable portfolio power
is the non-delivery reserve.

Missing evidence or failure to meet the response deadline yields zero dependable contribution.

## Event-triggered recalculation

`capacity_backtest.phase2.events` registers the evidence identities behind each envelope and
invalidates it after a matching material event. Supported triggers include outage revisions,
forecast vintages, SOC deviations, resource unavailability, reservation changes, network-model
revisions, measurement-quality failures, and operator constraints. Old, unrelated, or explicitly
non-material events do not invalidate a result.

## Phase and reactive power

`capacity_backtest.phase2.phase_power` requires explicit A/B/C allocation, phase reactive power,
unbalance limits, minimum power factor, reactive capability bounds, and control mode. Unknown
phase behavior must not be replaced with an ideal balanced assumption at an evidence boundary.

## Governed dependable envelope

`capacity_backtest.phase2.capacity` scales only the flexibility-supported portion above firm
capacity by dependable portfolio credibility. The resulting chronological envelope is guaranteed
to remain between Phase 1 firm and conditional envelopes. It retains `capacity_claim: false` and
adds blockers for:

- fatigue-limit violations;
- phase or reactive-power violations;
- battery terminal-SOC failure;
- incomplete cooling/workload recovery;
- absence of dependable delivery evidence.

This result establishes a reproducible dependable-capacity methodology. Operator topology,
ratings, protection settings, dispatch acceptance, telemetry, and contractual authorization are
still required before representing it as connectable capacity.
