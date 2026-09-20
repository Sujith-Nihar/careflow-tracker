# CareFlow Tracker

A healthcare voice-agent workflow where a call counts as handled only when persisted function
results and downstream-system state say so — never because the agent said so.

Built for the Kyron Medical full-stack take-home. A practice manager reported calls showing as
"resolved" when nobody had been transferred and no callback existed. This reproduces that failure
on a real voice call, fixes it in the flow's structure rather than its wording, and gives staff a
screen that shows what the agent promised next to what the systems recorded.

**Walkthrough video** (single take, unedited):
https://drive.google.com/file/d/1ECUwREK_7O3eHXD1Jec1m4CweCHPa5uu/view?usp=share_link

**Start with [`SUBMISSION.md`](SUBMISSION.md)** — the end-to-end trace, results, risks and what is
mocked. Measured voice-run results are in [`docs/RESULTS.md`](docs/RESULTS.md).

---

## What's in here

| Path | What it is |
|------|-----------|
| `backend/` | Flask API: four Vogent function endpoints, webhooks, simulators with fault injection, the pure `derive_status()` decision function, 98 tests |
| `frontend/` | Next.js investigation UI, server-side fetch only |
| `vogent/` | The two agent versions as code (`flows/v1.json`, `v2.json`), function definitions, sync and export scripts, and `export/` — the versions the reported runs actually used |
| `evals/` | Five scenarios as YAML, the deterministic metric set, the browser voice harness, and a no-cost replay path |
| `worker/` | Queue worker for asynchronous evaluation runs, with dead-letter handling |
| `infra/terraform/` | The AWS equivalent of that worker. Validates locally; not deployed |
| `artifacts/` | Every voice run preserved: dial records, transcripts, timelines, evidence bundles, metrics |
| `docs/` | Design documents, decisions, risks, investigations |

---

## Architecture

```
synthetic caller audio
        ↓
Vogent flow agent  (V1 baseline · V2 evidence-aware)
        ↓  HTTP function call
Flask API  — validates, runs the simulator under an injected fault,
             records the attempt and the result separately
        ↓
PostgreSQL — eight concepts kept apart: caller intent, agent promise,
             requested action, attempted action, action result,
             downstream record, derived status, staff action
        ↓
derive_status()  — pure, no I/O, and never given the transcript
        ↓
Next.js dashboard  ·  evaluation runner  ·  queue worker
```

The invariant: a `completed_*` status requires a downstream row in a success state, produced by an
action the backend actually handled. No transcript content can produce one. Details in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the decision table and its tests are in
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md).

**Stack:** Python 3.12 · Flask · psycopg 3 · PostgreSQL · Next.js 15 / TypeScript ·
Vogent (flows, functions, Web SDK) · Playwright · boto3 + `moto` · Terraform

---

## Setup

**No third-party API key is needed.** You supply three things: a PostgreSQL you control, and two
random strings you generate yourself. Everything below then runs — tests, the evaluation suite,
the dashboard, the worker and the AWS definition.

A Vogent key and a tunnel are needed *only* to place new voice calls. The calls behind the
reported results are already saved under `artifacts/`.

```bash
cp .env.example .env
```

Then fill in three values (the file marks which are required, and
[`docs/HUMAN_SETUP.md`](docs/HUMAN_SETUP.md) walks through it):

1. **`DATABASE_URL`** — `docker compose up -d db` gives you one, or point at any PostgreSQL 16
2. **Two org tokens** — `openssl rand -hex 24`, twice. Not an account, just two different strings
3. **`DEMO_ORGANIZATION_ID`** — printed by `make seed` in step 3 below; paste it back

```bash
make setup                    # Python dependencies
make migrate && make seed     # schema + the two synthetic practices
                              # ^ prints the practice ids — copy the demo one into .env
make api                      # evidence API on :5055
make ui-install && make ui    # dashboard on :3000
```

Port 5055, not 5000: macOS AirPlay Receiver occupies 5000.

---

## Run it

Everything here is free and needs no Vogent workspace:

```bash
make test          # 98 backend tests against real PostgreSQL
make replay        # all five scenarios end to end, no voice, no cost
make structural    # flow lint: V1 fails five checks, V2 passes
make worker-demo   # queue → worker → result, plus a poisoned job reaching the dead-letter queue
make tf-validate   # the AWS definition
make secret-scan   # fails if anything credential-shaped is tracked
```

Real voice runs need a Vogent workspace and a tunnel, and they cost money:

```bash
make setup-evals                          # Playwright + Chromium; not part of `make setup`
make tunnel                               # in a second terminal
make eval VERSION=v2                      # a voice call per scenario
make eval VERSION=v2 STRATEGY=optimized   # risk-based mix
```

`make help` lists every target.

---

## Results in brief

| | V1 baseline | V2 evidence-aware |
|---|---|---|
| Scenarios passed | **2 / 4** | **4 / 4** |
| Connected seconds | 197 s | 118 s |

The two versions agree where nothing goes wrong and diverge exactly where the practice policy
matters, which is what makes the comparison mean something. V1 is also the more expensive one: a
flow that never learns it has finished keeps talking.

Evaluating the same frozen version naively versus a risk-based mix: **$0.1770 → $0.0885** and
183 s → 156 s, with both high-risk paths kept on real voice. Every dollar figure is a
`CALCULATED_ESTIMATE` from measured connected seconds, labelled as such.

Full tables, per-case outcomes, the coverage given up and the one unstable metric:
[`docs/RESULTS.md`](docs/RESULTS.md).

---

## Documentation

**Read in this order**
[`ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the invariant, boundaries, failure semantics, logging ·
[`DATA_MODEL.md`](docs/DATA_MODEL.md) — tables and the derived-status decision table ·
[`API_DESIGN.md`](docs/API_DESIGN.md) — every HTTP contract ·
[`VOGENT_PLAN.md`](docs/VOGENT_PLAN.md) — verified vs. assumed Vogent behaviour, both flows ·
[`EVALUATION_PLAN.md`](docs/EVALUATION_PLAN.md) — scenarios, metrics, the two experiments

**Results and findings**
[`RESULTS.md`](docs/RESULTS.md) · [`INVESTIGATIONS.md`](docs/INVESTIGATIONS.md) — seven
investigations, each with the dial ids that prove it ·
[`MANAGER_UPDATE.md`](docs/MANAGER_UPDATE.md) — the plain-language update for the practice manager

**Reference**
[`PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) · [`DECISIONS.md`](docs/DECISIONS.md) ·
[`RISKS.md`](docs/RISKS.md) · [`UI_PLAN.md`](docs/UI_PLAN.md) ·
[`ASYNC_INFRA_PLAN.md`](docs/ASYNC_INFRA_PLAN.md) · [`HUMAN_SETUP.md`](docs/HUMAN_SETUP.md) ·
[`REQUIREMENTS_MATRIX.md`](docs/REQUIREMENTS_MATRIX.md)

---

All people, calls, policies and records are synthetic. No credentials are committed; `make
secret-scan` enforces it. The scheduler, the triage line and the callback queue are in-process
simulators — that boundary is `backend/app/simulators/`.
