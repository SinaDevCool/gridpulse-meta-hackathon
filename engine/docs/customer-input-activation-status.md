# Customer-input activation checkpoint

The user selected **Keep deployment synthetic-only** on 2026-10-23.

The existing Render pilot stays on its previously qualified fixed demonstration.
Automatic deployment is off. Do not route arbitrary customer inputs to it, expose
an unauthenticated solve endpoint, use production credentials, or change Supabase.

The 0.2.2 candidate adds exact nonnegative meter imports for negative energy prices
and prevents artificial post-completion workload consumption. Replay tariff
validation permits finite negative energy prices but not negative ancillary
charges. Remote regression and capped-container gates must pass before any
separate decision to update the synthetic pilot.

The app candidate adds disabled/no-battery mapping, terminal-capacity guards,
timestamp/resource reconciliation, bounded incumbent-gap acceptance and exact
submitted-snapshot reconciliation through the existing authenticated job API.
Workbench results use that common acceptance boundary, but do not replace the
heuristic Operations charts.

Remaining gates include full input classification/calibration, objective policy,
variable-allocation scope, shared UI selection and canonical presentation adapters,
authenticated staging and durable job-state qualification, realistic resource
benchmarks, shadow comparison and explicit production activation. Neither this
document nor a passing test suite establishes their completion.

Customer-input deployment needs a separately approved authentication/storage
configuration. The synthetic-only decision is not permission to create one or
to resume parked PR #37. No new queue, copied engine, or per-tab solver is needed.
