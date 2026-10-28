# GridPulse Meta hackathon source

GridPulse helps an energy manager investigate an accepted synthetic data-centre plan. Meta interprets questions and prioritises checked findings. The canonical Python engine calculates the quantities; the application retains warnings and evidence boundaries. No equipment control is authorised.

## What was built during the event

The existing planner and product predate this submission. Event work beginning 28 October 2026 adds verified-finding composition, repairs fresh exact-experiment submission and recovery, records individual provider stages, exports reviewed investigation evidence, and strengthens model evaluation. See `product/docs/meta-hackathon-delivery.md` and `product/docs/meta-hackathon-rules-checklist.md`.

`SOURCE_MANIFEST.json` identifies both source revisions and file hashes. This repository contains source snapshots without the private repositories' Git history. CVs, pitch/investor documents, office/PDF files, output folders and local credentials are excluded. Both original repositories remain private.

## Layout

- `product/`: frontend, Worker/copilot server, API source, tests and lockfile.
- `engine/`: optimisation, physical replay, calibration and backtests.
- `THIRD_PARTY_NOTICES/`: preserved third-party notices. MIT covers GridPulse-owned code only.

The engine's historical `.render-core` pointer records its original qualification dependency. Use the paired `product/services/grid-data` sources here; no access to a private submodule is needed for the installation below.

## Run the product

Use the Node version supported by `product/package.json` and the committed lockfile. From `product/`, run `npm ci`, copy `.env.example` to a local `.env`, supply your own supported public configuration, then run `npm run dev`. Server-only Meta credentials belong in ignored `.dev.vars`; never put them in `VITE_` variables. Use Standard `muse-spark-1.3` for this candidate.

Public synthetic planning and private exact experiments have different admission requirements. Configuration does not grant database access or authorise schema/billing changes. Without a qualified private backend, use the supported synthetic experience; do not bypass its gates.

## Verify without production writes

Run relevant Product tests through `npm run verify:local -- unit src/server/operations src/features/operations/copilot src/features/operations/hooks/experiment-lifecycle.test.ts`, followed by `npm run verify:local -- checks`. Heavy jobs are sequential; at most two unit workers and one browser worker. The Windows guard requires at least 3 GB free memory to begin.

For the Python checks, create a local virtual environment and install the paired source packages with the required extras: `python -m pip install -e "./product/services/grid-data[api,dev,study]" -e "./engine[dev,study]"`. Then run the focused experiment, facility HTTP integration, accounting, replay and calibration tests from `engine/`. Use one numerical thread. These tests use synthetic inputs and an in-memory API store.

The live Meta harness supports `COPILOT_QUALIFY_OFFLINE_FIXTURE=true` and an optional `COPILOT_QUALIFY_JOB_INPUT` file from a real local synthetic solve. It makes paid Meta calls but does not create Supabase accounts/jobs in this mode. Fixture mode is not a claim about a deployed service or measured facility. See the delivery document for commands and evidence classes.

## Evidence and limits

The full Product unit run passed 724 tests with one existing skip; subsequent targeted tests cover the final routing fix. Real Engine/API qualification passed 17 checks and its genuine output passed four frontend round-trip checks. Compiled fast browser checks and the required MILP journey passed locally. Evaluation reports distinguish display fixtures, genuine local synthetic solves, actual Meta calls and hosted execution.

Some capacity-ranking and national-alert research release gates remain failed; they do not support operational claims. Synthetic results are not measured savings, additional connection capacity, site safety certification or permission to dispatch. Review acknowledgement is not operational approval.

Hackathon video and final validation summary will be linked after final qualification. No unsupported completed-submission claim is made here.

## Event contribution and final qualification

See [event contributions](EVENT_CONTRIBUTIONS.md), the [code patch](HACKATHON_CHANGES.patch), and [final qualification](VALIDATION.md).
