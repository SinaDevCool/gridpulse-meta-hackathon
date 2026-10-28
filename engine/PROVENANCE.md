# Copied-code provenance

The `src/grid_data` calculation subset and matching focused tests were copied from:

- Repository: `GridPulse-Full`
- Source commit: `bb5806ba3800f1ed0af0c6e6c959d2a5c6826f13`
- Source path: `services/grid-data`
- Copied on: `2026-08-13`

The immutable SHA-256 inventory is stored at `data/manifests/copied-grid-data.sha256`.

The copy is intentional: this lab must run without importing or resolving the GridPulse repository. Future changes should be made here and documented; upstream synchronization must be an explicit reviewed operation, not an automatic filesystem dependency.

No UI, deployment configuration, credentials, raw operator data, or generated artifacts were copied.

The copied Berlin test was narrowed to the model-level safety assertions. Its GridPulse web-release artifact assertion was intentionally omitted because this repository does not contain or publish the web application's `public/` output.
