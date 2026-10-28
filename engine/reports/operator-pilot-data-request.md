# Operator pilot: minimum validation data request

## Recipients and boundary

For Stromnetz Berlin, E.DIS Netz and 50Hertz. Data may remain confidential, pseudonymised and
inside an operator-approved secure environment. Public reports will contain only agreed aggregate
validation metrics; topology, loading, customer requests, queues, reservations, protection data
and commercially sensitive outcomes will never be published.

## Essential fields

- Versioned anonymised network connectivity and stable asset IDs, including normal switching
  state and timestamped topology changes.
- Normal and emergency equipment ratings, units, validity periods, seasonal/dynamic-rating flags.
- Hourly or 15-minute loading for relevant lines and transformers, with UTC offset/time zone,
  quality flags, missingness semantics and revision timestamps.
- Planned and unplanned outages, publication/knowledge time, effective interval, affected assets,
  status, revision and reason.
- Contracted demand, accepted-but-not-connected demand, queued requests and reserved capacity at
  an agreed aggregation that prevents customer re-identification.
- Applicable N-1, protection, transfer, voltage and thermal policies with validity periods.
- Pseudonymised historical connection cases: request time, requested MW, assessed connection
  point, decision time, approved/rejected result, firm/conditional MW offered, reinforcement
  requirement and expected delivery date.

## Optional fields

- Planned generation/load forecasts, remedial-action activations, dynamic line ratings, power
  factor/reactive demand, curtailment eligibility, flexible connection contracts and backup-
  generation constraints.

## Acceptable anonymisation and aggregation

Stable random asset and case identifiers are sufficient; customer names, addresses and account
IDs are neither needed nor accepted. Coordinates may be replaced by published service area,
electrical zone or coarse cells if connectivity is preserved. Time may be hourly if 15-minute
data cannot leave the operator boundary. Values may be banded only if exact values remain
available inside the secure validation environment.

## Validation method

Freeze each prediction at its historical issue time, reconstruct only then-known revisions, hold
out whole years and network areas, and compare predicted risk and synthetic envelopes with actual
constraint events and connection-study outcomes. Calibration uses prior periods only. Results are
reported by year/season/area and missing-source period. No operator data automatically becomes a
public capacity claim; only an operator-reviewed result may enter the operator-confirmed layer.
