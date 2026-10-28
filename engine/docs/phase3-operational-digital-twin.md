# Phase 3 operational digital twin

## Status and authority boundary

Phase 3 is implemented as a deterministic operational digital twin, command-safety model, and
delivery-verification system. The repository does not connect to or control live PCC equipment.
Digital-twin readiness and live-dispatch authorization are separate gates. Live authorization
requires an explicit operator authorization identifier in addition to every technical gate.

## PCC telemetry

`capacity_backtest.phase3.telemetry` requires measurement identity, PCC identity, source,
timezone-aware timestamp, monotonic sequence, A/B/C voltage and current, active and reactive
power, frequency, and quality. It gates:

- freshness and future timestamps;
- replayed or out-of-order sequence numbers;
- invalid, suspect, or estimated quality;
- voltage and current limits;
- voltage/current unbalance;
- power factor;
- electrical plausibility.

Rejected telemetry cannot support conditional dispatch and causes the controller to use the firm
fail-safe limit.

## P/Q feedback setpoints

`capacity_backtest.phase3.controller` calculates bounded active-power limits and reactive-power
setpoints using explicit gains, damping, target voltage, reactive bounds, and active ramp limits.
Accepted telemetry uses the dependable conditional envelope. Rejected telemetry uses the Phase 1
firm envelope. Feedback cannot expand either envelope.

## Command lifecycle

`capacity_backtest.phase3.commands` implements:

- explicit dispatch authorization;
- unique command identity and idempotency key;
- PCC, resource, and envelope identity;
- issued, effective, and expiry timestamps;
- P/Q setpoints and ramp limits;
- pending, acknowledged, rejected, timed-out, cancelled, and completed states;
- acknowledgement deadlines;
- prevention of duplicate commands with changed content.

## Fail-safe state machine

`capacity_backtest.phase3.failsafe` uses explicit disarmed, armed, dispatching, degraded,
safe-limit, and locked-out states. Telemetry or resource degradation removes normal confidence.
Acknowledgement timeout, delivery failure, or stale capacity envelope transitions to the firm
safe limit. Manual lockout dominates all automatic states and requires an explicit reset.

## Delivery verification

`capacity_backtest.phase3.delivery` compares post-command PCC measurements with the frozen
baseline and commanded active/reactive setpoint. It verifies telemetry acceptance, active MW
delivery, reactive Mvar delivery, tolerances, and response time. Each result exports a verified
`DeliveryEvidence` record directly consumable by the Phase 2 credibility model. Failed-quality
telemetry is never admitted as verified delivery evidence.

## Replayable digital twin

`capacity_backtest.phase3.simulation` replays chronological telemetry, command, acknowledgement,
delivery, stale-envelope, resource-failure, and lockout events. The log is a SHA-256 hash chain:
each entry commits to its content and the preceding entry. Replaying the same inputs produces the
same final hash. The simulation reports delivery failures, acknowledgement timeouts, and fail-safe
entries and always states `automatic_live_dispatch_authorized: false`.

## Operational readiness

`capacity_backtest.phase3.readiness` carries forward every Phase 2 blocker and additionally
requires configured telemetry, command channel, acknowledgements, tested fail-safe behavior, and
delivery verification. Passing these gates enables digital-twin dispatch testing. Live dispatch
also requires explicit operator authorization and appropriate external security, contractual,
hardware, and regulatory controls that remain outside this repository.
