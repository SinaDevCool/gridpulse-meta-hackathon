# Capacity-only implementation

## Purpose

The canonical `capacity_backtest.capacity_study` package calculates an evidence-governed,
chronological available-import screening envelope for one data-centre site and multiple possible
PCCs. It reuses the existing Pandapower AC solver and Phase 2 flexibility models. It does not
create a second electrical solver or promote reconstructed inputs to operator-confirmed facts.

## Authoritative flow

1. Load a manifested canonical, SimBench, or explicitly mocked network.
2. Generate or accept candidate PCCs.
3. Build seeded network-parameter realizations with Latin-hypercube sampling.
4. Assemble chronological background load, generation, commitments, reservations, and outages.
5. Generate exhaustive modeled line and transformer N-1 cases.
6. Run bounded AC incremental-import searches for every state and realization.
7. Aggregate chronological availability separately from cross-realization uncertainty.
8. Record operator-data blockers and reject a capacity claim.
9. Persist JSON, Markdown, and a hash manifest in the OneDrive `runs/` directory.

## Capacity semantics

- Firm screening capacity is the probability-weighted P50 of each realization's chronological
  minimum. P10/P50/P90 describe uncertainty across realizations.
- Availability capacities describe the empirical duration curve across solved states. They do
  not represent confidence intervals.
- Curtailment hours, MWh, event count, and longest event are calculated at the requested site MW.
- A result at the configured search ceiling is marked as a lower bound (`>=`), never as a precise
  constraint.
- Flexibility is assessed through the existing Phase 2 battery, cooling, workload, fatigue,
  phase-power, and credibility models. It does not alter the physical network envelope.

## Missing operator data

Missing topology, ratings, nodal loading, queue, switch/tap history, or reviewed contingencies may
be replaced only by explicitly reconstructed or synthetic realizations. The configuration records
that state and the result includes structured blockers. Protection, short-circuit, harmonics,
dynamic stability, and final reactive requirements remain operator-study blockers.

## Run the included mock study

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m capacity_backtest.cli capacity run --study config/studies/capacity_screening_mock.yaml
```

The mock study exists to verify mechanics. Replace `network.mode` with `canonical_json` and provide
a normalized network path, or use `simbench` with a valid SimBench code for reference validation.
The output is stored under:

```text
%OneDrive%\GridPulse Capacity Research Data\runs\gridpulse-capacity-study-run-v1\<run-id>\
```

Local storage remains limited to staging, caches, solver scratch state, locks, logs, active model
runs, and live Neo4j data.
