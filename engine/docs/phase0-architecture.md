# Phase 0 architecture

## Status

Phase 0 is implemented. It consolidates the contracts and safety gates that every later
forecasting, network, flexibility, reliability, and operational-simulation phase must use.

## Canonical ownership

| Concern | Owner |
|---|---|
| Truth classes and capacity-claim authorization | `capacity_backtest.contracts` |
| Evidence and run provenance | `capacity_backtest.domain.evidence` |
| Forecast distributions | `capacity_backtest.domain.forecast` |
| Chronological N-0/N-1 envelopes | `capacity_backtest.domain.network` |
| Flexibility portfolios and resources | `capacity_backtest.domain.resources` |
| Study inputs | `capacity_backtest.domain.scenario` |
| Dispatch and capacity results | `capacity_backtest.domain.results` |
| Study orchestration | `capacity_backtest.pipeline` |
| Electrical calculation kernels | `grid_data` |
| Immutable storage and artifact writing | `capacity_backtest.storage` |

Existing experiment modules remain supported. New algorithms must consume the canonical
contracts at their public boundary and must not introduce a competing scenario, provenance,
or capacity-result schema.

## Required study flow

Every capacity study follows one ordered path:

1. Validate evidence, scenario, forecast, network envelope, and provenance.
2. Require exact forecast/envelope timestamp alignment.
3. Run network screening.
4. Require detailed physics verification.
5. Optimize or simulate chronological dispatch.
6. Build and validate the capacity-envelope result.
7. Preserve scenario identity and the exact provenance fingerprint.
8. Reject promotion of non-operator inputs to operator-confirmed capacity.

`StudyPipeline` fails closed if detailed verification is absent or false. A surrogate may
prioritize physics cases, but it cannot bypass the verifier.

## Artifact requirements

Derived artifacts use a versioned manifest and carry:

- artifact and input SHA-256 hashes;
- creation time and evidence cutoff;
- canonical truth class and `capacity_claim: false` default;
- code and transformation versions;
- assumption-set identity;
- solver name and version;
- limitations.

Capacity claims remain restricted to `operator_confirmed` evidence by
`assert_capacity_claim_allowed`.

## Compatibility policy

The legacy labels `synthetic_benchmark_truth` and `synthetic_scenario` are accepted only at
old-data boundaries and immediately normalized. New outputs use `TruthClass` values. Unknown
labels are rejected rather than interpreted.

## Golden conformance suite

`tests/fixtures/golden_phase0_cases.json` fixes the expected behavior for:

- an unconstrained connection;
- a thermal constraint;
- an N-1 binding constraint;
- an energy-limited battery;
- evidence newer than the declared cutoff.

The domain and pipeline tests additionally lock down N-1 ordering, chronological uniqueness,
forecast/envelope identity, provenance fingerprints, mandatory physics verification, and
synthetic-claim rejection. Add a golden case before changing any of these behaviors.

## Extension rule for later phases

Later phases may add fields through a new schema version or add specialized calculation
modules behind the pipeline protocols. They must not weaken truth classification, provenance,
physics verification, chronological alignment, or capacity-claim authorization.
