# CareFlow Tracker

A narrow, production-minded vertical slice of a healthcare voice-agent workflow, built for the Kyron
Medical take-home. The problem: calls were marked "resolved" because the agent *said* a transfer or
callback happened. The fix: completion is derived only from persisted function results and downstream
system state, the agent's flow branches on those results, and staff see promise and evidence side by side.

**Status:** planning complete; implementation not started. See `docs/PROJECT_PLAN.md`.

## Architecture at a glance

Vogent flow agent (V1 baseline, V2 evidence-aware) → Flask API (validation, idempotency, simulators,
deterministic status derivation) → PostgreSQL (evidence) → Next.js investigation UI and a Python
evaluation runner that drives real browser voice calls with synthetic audio. An SQS-style worker runs
evaluations asynchronously; Terraform describes the AWS equivalent. Details: `docs/ARCHITECTURE.md`.

## Stack

Python 3.12 · Flask · psycopg 3 · PostgreSQL (Supabase or Docker) · Next.js 15 / TypeScript ·
Vogent (flows, functions, Web SDK) · Playwright · boto3 + `moto` (local SQS) · Terraform.

## Setup and run (to be finalized in Phase 10)

```bash
cp .env.example .env            # fill values per docs/HUMAN_SETUP.md
make setup                      # Python deps, Playwright Chromium, frontend deps
make migrate && make seed       # schema + demo organization + replayed scenarios
make api                        # Flask on :5000
make ui                         # Next.js on :3000
make test                       # backend tests
make replay                     # scenarios A–E through the backend without voice
make eval VERSION=v2 SCENARIOS=A,B,C,D   # real Vogent voice runs (needs workspace credentials)
```

## Documentation

`docs/ARCHITECTURE.md` · `docs/DATA_MODEL.md` · `docs/API_DESIGN.md` · `docs/VOGENT_PLAN.md` ·
`docs/EVALUATION_PLAN.md` · `docs/UI_PLAN.md` · `docs/ASYNC_INFRA_PLAN.md` · `docs/PROJECT_PLAN.md` ·
`docs/REQUIREMENTS_MATRIX.md` · `docs/DECISIONS.md` · `docs/RISKS.md` · `docs/HUMAN_SETUP.md` ·
`docs/SUBMISSION_CHECKLIST.md`. Orientation for coding agents: `CLAUDE.md`.

All people, calls, and records are synthetic. No credentials are committed.
