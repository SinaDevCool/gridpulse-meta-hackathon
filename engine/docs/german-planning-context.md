# German planning contract additions

The product constructs Europe/Berlin local days as contiguous UTC intervals. The
engine accepts 92/96/100 quarter-hour intervals through the existing request path;
it does not reinterpret local timestamps or retrieve market data during a solve.

Optional `facility.import_limit_profile_mw` and
`policy.operating_target_profile_mw` align one value per interval. Import limits
cannot exceed the facility ceiling. Solver bounds, physical replay, experiment
metrics and plan evidence use the same interval limits. Scalar-only requests retain
their existing behavior. Metadata in `planning_context` is transported and included
in request identity, but does not confer operator permission or legal compliance.

Accounting v1 remains energy-only. Accounting v2 requires explicit reviewed tariff
inputs; supplier and network energy charges use elapsed MWh. Incremental annual
capacity liability is the increase above the supplied prior billing peak times
EUR/kW/year; it is not a prorated daily charge or a complete invoice.

Battery permissions, protected reserve, terminal energy, workload constraints,
cooling, replay and calibration retain their existing owners. No second solver or
learned physical model is introduced. New source measurements are still required
for calibration; synthetic qualification does not establish delivered flexibility.

Coordinate product/API and engine releases before enabling the product's optional
German planning controls. Production activation and live SMARD verification are
outside this implementation qualification.
