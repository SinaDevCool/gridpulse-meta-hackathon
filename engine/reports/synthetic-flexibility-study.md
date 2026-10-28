# Synthetic DeFlex-style flexibility study

## Classification and boundary

- Truth class: **synthetic benchmark**
- Real-network or Berlin capacity claim: **No**
- Operator reconciliation: **Unavailable**
- Evaluated dispatch summaries: **800**
- Site demand scenarios: **10, 25, 50, 100 and 200 MW**

Each summary is an 8,760-hour deterministic dispatch against paired synthetic AC N-0 and N-1
envelopes. The policy permits a 10% interruptible share, at most four consecutive interruption
hours, 120 interruption hours per year, four-hour recovery, battery power equal to 25% of site
load, one hour of battery energy, 92% charge/discharge efficiency, 10% reserve state of charge,
and a 50%-of-site-load hourly import ramp. Backup generation is zero.

## Observed synthetic ranges

- Constrained hours: **0 to 8,760 per year**
- Curtailed or shifted energy: **0 to 2,400 MWh**
- Battery equivalent cycles: **0 to 0.828**
- Hours above the paired firm synthetic envelope: **0 to 8,760**
- Unserved energy: **0 to 1,445,234.4 MWh**

The very large upper constrained/unserved values occur where a site scenario exceeds the
synthetic N-1 envelope and the explicitly bounded flexibility resources cannot close the gap.
They are evidence against treating flexibility as an arbitrary capacity multiplier. They are not
forecasts for Berlin or any real site. Detailed per-family, node, operating-scenario and site-size
results, including N-0/N-1 binding constraints, rebound, battery use and ending recovery backlog,
are in `reports/backtest-results.json`.

## Release decision

The synthetic capacity gate and ranking gate both **FAIL**. The flexibility study is suitable only
as a deterministic mechanics benchmark. It cannot support available-MW, connection-feasibility,
or operational-reliability claims.
