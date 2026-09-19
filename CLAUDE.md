# CareFlow Tracker — Project Orientation

Kyron Medical full-stack take-home. A healthcare voice-agent workflow where a call counts as complete
only when persisted function and downstream-system evidence says so, never because the agent said so.
Assignment: `docs/ASSIGNMENT.md`. Limits: 16 active hours (`TIME_LOG.md`), 48-hour window from
2026-09-18 22:00 local. All data is synthetic. Commit only when asked, in small topic-grouped commits with short plain messages and no AI attribution trailer.

## Read in this order

1. `docs/ARCHITECTURE.md` — problem, invariant, boundaries, sequences, failure semantics, correlation, logging
2. `docs/DATA_MODEL.md` — tables, constraints, action outcomes, derived-status decision table
3. `docs/API_DESIGN.md` — every HTTP contract
4. `docs/VOGENT_PLAN.md` — verified vs. assumed Vogent facts, functions, flows V1 and V2, artifacts, billing
5. `docs/EVALUATION_PLAN.md` — scenarios, metrics, harness, the two experiments, investigation procedure
6. `docs/PROJECT_PLAN.md` — triage, budget, critical path, gates, phases with acceptance criteria, cut order
7. `docs/REQUIREMENTS_MATRIX.md`, `docs/DECISIONS.md`, `docs/RISKS.md`, `docs/UI_PLAN.md`,
   `docs/ASYNC_INFRA_PLAN.md`, `docs/HUMAN_SETUP.md`, `docs/SUBMISSION_CHECKLIST.md`, `docs/INVESTIGATIONS.md`

## Current state

Phases 0–2 done. Supabase and Vogent are both connected (`make db-check`, `make vogent-check`).
Schema applied to `public` and `careflow_test`; organizations seeded. The backend runs the full
Vogent boundary: four function endpoints, webhooks, simulators with fault injection, idempotency,
organization scoping, validation, structured logs, and the evidence API the UI and evaluator read.

**Next: Phase 3** (replay fixtures and `make replay`) in `docs/PROJECT_PLAN.md §5`, then Phase 4
(Vogent functions and the V1/V2 flows), which needs `docs/HUMAN_SETUP.md` section D (ngrok).

## Priorities (non-negotiable; cut from the bottom)

1. Promise ≠ evidence. Eight concepts stay separate (`ARCHITECTURE.md §2`); no single generic status field.
2. Function and downstream state are authoritative; the transcript is evidence of the promise only.
   Absence of evidence is never completion.
3. Real Vogent browser voice runs are mandatory for scenarios A–D on V1 and V2. Replay, structural
   checks, and unit tests never substitute.
4. Evaluation is a subsystem built alongside the app, with deterministic state-based metrics.
5. V1 is a plausible baseline, V2 an evidence-aware revision; compare with real runs, record what happened.
6. Investigate at least one failure or surprise; write it in `docs/INVESTIGATIONS.md` immediately.
7. Measure the naive full-voice suite, then a cheaper strategy on the same frozen version; report
   savings and coverage loss honestly; C and D always stay on voice.
8. Preserve evidence as it is produced under `artifacts/`; label dollars ACTUAL_BILLED or CALCULATED_ESTIMATE.
9. Order when time is short: state model → backend evidence → real voice → scenarios → metrics →
   V1/V2 → investigation → baseline measurement → optimized measurement → UI → worker/IaC → hardening → polish.

## Terminology (use exactly these)

organization (not tenant) · call (one Vogent dial) · action execution · agent statement (promise or
disclosure) · downstream record (appointment, transfer session, callback request) · derived status ·
scenario · evaluation run / evaluation case · fault profile · versioned prompt (a Vogent agent version).

## Repository layout

```
backend/    Flask app: api/ services/ simulators/ domain/ persistence/ observability/, migrations/*.sql, tests/
frontend/   Next.js investigation UI (server-side fetch only)
evals/      scenarios/*.yaml, fixtures/, runner/ (harness, metrics, replay, structural), caller_page/
vogent/     functions/*.json, flows/v1.json v2.json, scripts/sync.py export.py, export/ (what actually ran)
worker/     SQS-compatible worker, bootstrap, enqueue, DLQ inspection
infra/terraform/   SQS + DLQ, ECS task, IAM, SSM, CloudWatch (validate only)
artifacts/  spike/ v1/ v2/ efficiency/{baseline,optimized}/ investigations/ worker/
docs/       design documents listed above; SUBMISSION.md and MANAGER_UPDATE.md are written in Phase 10
```

## Working rules

- Python 3.12, Node 22, PostgreSQL via `DATABASE_URL` (Supabase or Docker). Plain SQL migrations, psycopg 3.
- Secrets only in `.env`; never in code, logs, artifacts, screenshots, or `NEXT_PUBLIC_*`. Run `make secret-scan` before submitting.
- Structured JSON logs with the events in `ARCHITECTURE.md §9`; never log params text, phone numbers, names, transcripts, tokens.
- Every query takes `organization_id`. Every Vogent function route is idempotent on `(dial_id, function, params)`.
- `derive_status()` is pure and lives in `backend/app/domain/derive_status.py`; every decision-table row has a test.
- Business failures return HTTP 200 with a `status` field (D7). Never retry transfers (D8).
- Save run artifacts and investigation notes the moment they exist. Update `TIME_LOG.md` at phase boundaries.
- Fictional policy is the only clinical rule (`ASSIGNMENT.md`); never diagnose or invent rules in prompts.
