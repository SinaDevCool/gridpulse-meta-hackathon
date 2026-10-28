# Grid-capacity backtest report

## Outcome

- Ranking release gate: **FAIL**
- Capacity-band release gate: **FAIL**
- Berlin available capacity: **Unknown - operator evidence required**

## Validation metrics

- Evaluated cases: 640
- Unique candidate nodes: 15
- Held-out network families: 8
- Mean absolute error: 58.742 MW
- Median absolute error: 43.0 MW
- Overstatement rate: 21.9%
- Severe overstatement rate: 16.2%
- Interval coverage: 85.0%
- Top-10 recall: 22.5%

- Contingency-selector recall: 29.7%
- Exhaustive contingency audit cases: 64
- Graph contingency reduction: 83.9%
- Topology provider: deterministic_in_memory

## Interpretation

The benchmark uses real public Berlin map anchors with synthetic electrical parameters. It validates calculation mechanics only; it is not a model of live Berlin capacity. 8 deliberately distinct synthetic network families are evaluated with each target family held out from calibration. Exhaustive N-1 physics audits a stratified subset; graph selection is measured there and never calculates MW. Ranking and capacity bands remain blocked unless every safety gate passes.
