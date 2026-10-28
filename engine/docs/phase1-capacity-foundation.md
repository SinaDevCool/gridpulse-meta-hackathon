# Phase 1 capacity and backtest foundation

## Status

Phase 1 is implemented as a research and validation layer. Its results retain their Phase 0
truth class and cannot become an operator capacity claim without operator-confirmed evidence.

## Implemented capabilities

### Bottom-up probabilistic forecasting

`capacity_backtest.phase1.forecasting` fits separate models for IT load, cooling, auxiliaries,
battery charging, and on-site generation. Training observations must precede the forecast
issue time. Component predictions are reconciled into net site demand with monotonic forecast
quantiles. Metrics include MAE, RMSE, interval coverage, underprediction frequency, and maximum
underprediction. Rolling-origin evaluation refits each immutable forecast vintage using only
observations strictly older than its issue time.

### Chronological AC envelope studies

`capacity_backtest.phase1.ac_envelope` reuses the existing `grid_data.network_study` provider.
For each operating state it includes committed load, generation, reactive power, reservations,
and the reviewed contingency set. It produces separate N-0 and N-1 import envelopes, binding
cases, binding constraints, search tolerance, and lower-bound flags.

The Phase 1 result covers steady-state AC thermal and voltage behavior. Protection,
short-circuit, harmonics, unbalanced three-phase analysis, and dynamic stability remain explicit
unknown constraints rather than being silently assumed safe.

### Physics-informed surrogate screening

`capacity_backtest.phase1.surrogate` trains only from records marked as physics verified. It
predicts approximate capacity, feasibility probability, and likely binding constraint. It
abstains when a feature is outside the training domain. All predictions set
`requires_detailed_verification`; the surrogate never authorizes capacity.

### Risk-limiting policy backtests

`capacity_backtest.phase1.risk` compares:

- a static margin;
- forecast quantiles;
- chance-constrained admission;
- conditional value-at-risk;
- distributionally robust admission;
- a perfect-foresight oracle.

Reported metrics include unsafe hours, empirical violation probability, unserved energy,
utilized energy, conservatism, and calibration error. The recommended policy is selected only
from non-oracle policies satisfying the empirical risk limit when one exists.

### Multi-horizon studies

`capacity_backtest.phase1.horizons` uses the same Phase 0 scenario and result contracts for
day-ahead, week-ahead, seasonal, and connection-planning studies. Each horizon has independent
point-count, quantile, and uncertainty-model requirements. An hourly forecast cannot be
silently stretched into a planning forecast.

## Required execution order

1. Build an evidence-cutoff-safe bottom-up forecast.
2. Construct chronological operating states.
3. Run surrogate screening or go directly to detailed analysis.
4. Run the AC N-0/N-1 envelope study.
5. Evaluate risk-limiting policies against actual held-out demand.
6. Build the canonical Phase 0 capacity-envelope result.
7. Repeat under the horizon-specific uncertainty contract.

## Remaining boundary

Phase 1 validates methods on synthetic, benchmark, public-context, or approved operator-model
inputs. It does not infer live free capacity from public data. Actual PCC topology, equipment
ratings, switching state, protection settings, outages, reservations, queue commitments, and
operator acceptance remain required for a site-specific capacity claim.
