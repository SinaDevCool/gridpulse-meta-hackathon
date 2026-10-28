# Live upstream-context backtest

## Outcome

- Training observations: 34,893 hourly rows
- Frozen held-out period: 2025 (8,760 hourly rows)
- Geographic measurement: Germany-Luxembourg bidding zone
- Regional or substation measurement: **No**
- Available connection capacity: **Unknown**

## Model results

- ridge_load_lags_only: **succeeded**; MAE 1336.0 MW; RMSE 1735.2 MW
- mean_baseline: **succeeded**; MAE 7796.2 MW; RMSE 9325.8 MW
- ridge: **succeeded**; MAE 1296.8 MW; RMSE 1696.7 MW
- tabpfn: **succeeded**; MAE 452.4 MW; RMSE 600.4 MW

## Added evidence

- DWD temperature lag features active: **Yes**
- Wind and solar generation enter through past lags only.
- Congestion and outage features: **Unavailable; not encoded as zero**

## Stress classifier gate

- 2022: Brier 0.013; precision 66.4%; recall 94.9%; false-negative rate 5.1%
- 2023: Brier 0.009; precision 16.7%; recall 100.0%; false-negative rate 0.0%
- 2024: Brier 0.020; precision 37.8%; recall 96.6%; false-negative rate 3.4%
- 2025: Brier 0.022; precision 54.9%; recall 99.0%; false-negative rate 1.0%

Release gate: **FAIL**. Recall is high, but precision is not stable enough for operational alerts.

## Interpretation

These metrics measure next-hour national-system load prediction from calendar and historical-load lags. They do not measure free-capacity prediction error. The series may support upstream stress scenarios for Berlin, Brandenburg, Bremen, Frankfurt and Rhine-Main, but must not be allocated to those regions or to public map nodes as measured load. Operator topology, ratings, outages, reservations, queues, protection limits and connection-study outcomes remain unavailable.
