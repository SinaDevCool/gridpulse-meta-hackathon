# Render Free pilot release gates

Scope: a separate, free-only Frankfurt staging service. Do not alter existing
Render services, production app routing, Supabase schema, or parked PR #37.

1. Run `render-free-qualification.yml` remotely. It builds the existing API and
   private engine together from exact revisions. Docker enforces 512 MiB with no
   swap, 0.1 CPU and one test process. Numerical libraries use one thread.
2. Inspect exit code, OOM status, sampled container memory and test reports.
   Docker samples may miss short peaks; passing small fixtures is necessary but
   not sufficient. Add representative 96-interval portfolios before release.
3. Approve a staging authentication and durable job-store configuration. The
   existing API intentionally disables execution without credentials. Never
   bypass authentication or copy production secrets. Do not introduce a second
   queue or assume free hosting provides a standalone background worker.
4. Build a runtime-only immutable artifact (no tests, credentials or Git history),
   qualify dependency versions and cancellation, then deploy the same artifact.
5. Create only a `free` web service in the confirmed workspace, auto-deploy off,
   explicit health check and exact candidate identity. Private image/repository
   access must be configured through supported secret storage.
6. Verify real authenticated submission, polling, cancellation and accepted
   replay. Display cold-start/restart limitations. Keep production MILP disabled.

Free Render services sleep and lose local filesystem state. Workspace free hours
are shared with existing services. Never use artificial keepalive traffic or
silently upgrade plans. Failure of a gate stops deployment; report the evidence.
