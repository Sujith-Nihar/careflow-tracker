# CareFlow Tracker

A narrow, production-minded vertical slice of a healthcare voice-agent workflow, built for the Kyron
Medical take-home. The problem: calls were marked "resolved" because the agent *said* a transfer or
callback happened. The fix: completion is derived only from persisted function results and downstream
system state, the agent's flow branches on those results, and staff see promise and evidence side by side.

**Status:** built and evaluated end to end on real Vogent voice calls. Start with `SUBMISSION.md`; measured results are in `docs/RESULTS.md`.

## Architecture at a glance

Vogent flow agent (V1 baseline, V2 evidence-aware) → Flask API (validation, idempotency, simulators,
deterministic status derivation) → PostgreSQL (evidence) → Next.js investigation UI and a Python
evaluation runner that drives real browser voice calls with synthetic audio. An SQS-style worker runs
evaluations asynchronously; Terraform describes the AWS equivalent. Details: `docs/ARCHITECTURE.md`.

## Stack

Python 3.12 · Flask · psycopg 3 · PostgreSQL (Supabase or Docker) · Next.js 15 / TypeScript ·
Vogent (flows, functions, Web SDK) · Playwright · boto3 + `moto` (local SQS) · Terraform.

## Setup and run

**No third-party API key is needed.** You supply a PostgreSQL you control and two random
strings you generate yourself (`openssl rand -hex 24`); everything below then runs, including
the tests, the evaluation suite, the worker and the AWS definition. A Vogent key and an ngrok
domain are needed only to place *new* voice calls — the calls behind the reported results are
already saved under `artifacts/`.

```bash
cp .env.example .env            # DATABASE_URL + two tokens, per docs/HUMAN_SETUP.md
make setup                      # Python deps
make migrate && make seed       # schema + the two synthetic practices
#                                 seed prints the practice ids: copy the demo one
#                                 into .env as DEMO_ORGANIZATION_ID before `make ui`
make test                       # backend tests against real PostgreSQL
make api                        # Flask on :5055 (5000 is taken by macOS AirPlay)
make ui-install && make ui      # Next.js dashboard on :3000
```

No Vogent credentials are needed for any of the above, nor for the paths that cost nothing:

```bash
make replay        # scenarios A–E through the backend without voice
make structural    # flow lint: V1 fails five checks, V2 passes
make worker-demo   # queue, worker, poisoned job, dead-letter queue
make tf-validate   # the AWS definition
```

Real voice runs need a Vogent workspace and a tunnel (`make tunnel`), and they cost money:

```bash
make setup-evals                          # Playwright + Chromium, not part of `make setup`
make eval VERSION=v2 SCENARIOS=A,B,C,D
```

## Documentation

`docs/ARCHITECTURE.md` · `docs/DATA_MODEL.md` · `docs/API_DESIGN.md` · `docs/VOGENT_PLAN.md` ·
`docs/EVALUATION_PLAN.md` · `docs/UI_PLAN.md` · `docs/ASYNC_INFRA_PLAN.md` · `docs/PROJECT_PLAN.md` ·
`docs/REQUIREMENTS_MATRIX.md` · `docs/DECISIONS.md` · `docs/RISKS.md` · `docs/HUMAN_SETUP.md` ·
`docs/SUBMISSION_CHECKLIST.md` · `docs/RESULTS.md` · `docs/INVESTIGATIONS.md`.
Orientation for coding agents: `CLAUDE.md`.

All people, calls, and records are synthetic. No credentials are committed.
