# Project Plan

Owner of: the initial triage (kept verbatim for the submission), the phase sequence, gates, critical
path, and cut order. Design content lives in the documents it links to.

---

## 1. Triage (initial plan, written before implementation)

**Model of the failure.** "Resolved" is being derived from what the agent said or from the flow reaching
the transfer step, not from a downstream result. Three mechanisms: the flow speaks before verifying; no
failure branch creates the callback; status comes from the agent's own disposition or an extractor.
Details: `ARCHITECTURE.md §1–2`.

**Verify first.** The real Vogent function payload (`dial.inputs`, transcript snapshot); whether an
`Equal` rule on a function output routes; function timeout/retry behavior; that a Playwright-driven
browser can complete a call with injected audio. `VOGENT_PLAN.md §2`.

**Smallest outcome.** Scenarios A–D on real browser calls against V1 and V2, backend evidence with
deterministic derivation, an investigation UI, two measured evaluation strategies, a local async worker
with Terraform.

**First three priorities.** (1) Evidence model and derivation; (2) Flask boundary and simulators verified
by replay; (3) real Vogent flows and voice evaluations. **Deferred:** request signatures, authentication,
organization switcher, LLM judge, CI, accessibility, live AWS, stretch scenarios (unverified transfer,
off-policy request, mid-call intent switch).

**Evidence that would change the plan.** `VOGENT_PLAN.md §2` (assumptions A1–A6 with fallbacks);
harness gate in `EVALUATION_PLAN.md §5`; if V1 does not reproduce the failure on voice, report it.

**Questions.** To the practice: where does today's "resolved" come from; callback turnaround and owner;
should staff completion close the call automatically. To Kyron: function retry/timeout and signature
behavior; `transfer` functions on browser calls (assumed no); usage/billing API (assumed none).

**Recorded assumptions.** Transfer verified ⇔ simulator returns `connected`; one agent, two versions;
scenario IDs pre-registered by `dial_id`; dollars are estimates from `aiDurationSeconds × $0.0015` unless
the Billing tab shows charges; function timeout ≥ 10 s.

---

## 2. Budget

| Bucket | Hours |
|--------|-------|
| Planning and design review (spent) | 1.50 |
| Implementation phases 0–10 (below) | 12.75 |
| Buffer (Vogent debugging first, then anything on the critical path) | 1.75 |
| **Total** | **16.00** |

Scope was removed to make this fit (§6). Estimates are for active, focused time.

## 3. Critical path

```
Phase 1 schema + derive_status ─▶ Phase 2 Flask functions + simulators ─▶ Phase 3 replay proves A–E
   ─▶ Phase 4 tunnel + functions + V1/V2 flows + first real call ─▶ Phase 5 harness + runner + metrics
   ─▶ Phase 6 V1/V2 voice runs + investigation ─▶ Phase 7 efficiency experiment ─▶ Phase 8 UI (trace complete)
   ─▶ Phase 10 submission
```
Phase 9 (worker/Terraform) is off the critical path and can be dropped to buffer if needed.
Parallelizable without conflict: UI shell (after Phase 2 freezes `/api/calls` contract), Terraform files
(after Phase 9's job contract is written), `SUBMISSION.md` skeleton (any time). One implementer owns
`backend/app/domain` and `backend/app/api` at a time.

## 4. Gates

| Gate | Before | Condition |
|------|--------|-----------|
| A — Domain correctness | Phase 4 | `derive_status` tests cover every row of `DATA_MODEL.md §5`; replay of A–E yields expected statuses |
| B — External boundary | Phase 5 | Function endpoints idempotent, organization-scoped, validated; one real call captured end to end |
| C — Correlated trace | Phase 6 | One voice call traceable scenario → dial → executions → derived status → evidence bundle |
| D — Trustworthy suite | Phase 7 | A–D produce PASS/FAIL (not ERROR) on V2; at least one investigation written |
| E — Submission | Phase 10 | `SUBMISSION_CHECKLIST.md` evidence gates all ticked before any polish |

## 5. Phases

Each phase: objective · why · dependencies · steps · files · acceptance · verification · artifacts ·
time · stop · defer-if-overrun · risks · fallback.

### Phase 0 — Preflight and foundation (0.50 h)
Objective: environment proven, repo tooling in place, no application logic.
Why: every later phase assumes DB, Vogent API, and tunnel connectivity.
Dependencies: `HUMAN_SETUP.md` A–D complete.
Steps:
1. `backend/pyproject.toml` (Flask, psycopg[binary], pydantic, structlog, pytest, playwright, boto3, pyyaml, requests); `make setup`.
2. `Makefile` targets: `setup`, `migrate`, `migrate-test`, `db-check`, `vogent-check`, `tunnel`, `api`, `ui`, `test`, `replay`, `eval`, `worker`, `secret-scan`.
3. `docker-compose.yml` with Postgres for reviewers (not used by the candidate).
4. `scripts/db_check.py`, `scripts/vogent_check.py` (lists agents with the key; prints nothing secret).
5. `.env` filled by the human; `make db-check && make vogent-check` pass.
Files: `Makefile`, `backend/pyproject.toml`, `docker-compose.yml`, `scripts/`.
Acceptance: both checks pass; `make tunnel` serves `/healthz` stub publicly.
Artifacts: none. Stop: checks green. Defer: compose file. Risk: ngrok domain claim. Fallback: cloudflared.

### Phase 1 — Domain model, persistence, status semantics (1.25 h)
Objective: authoritative state exists and the decision table is code.
Why: R5, R10, R23 — the invariant lives here.
Dependencies: Phase 0.
Steps:
1. `backend/migrations/0001_schema.sql` from `DATA_MODEL.md §3` including all unique/check constraints; `0002_seed.sql` with `org_demo`, `org_other`, token hashes from env at seed time.
2. `backend/app/persistence/db.py` (connection, transaction helper) and `repositories.py` (one function per query; every function takes `organization_id`).
3. `backend/app/domain/types.py` (dataclasses/enums for outcomes, statuses, statements).
4. `backend/app/domain/derive_status.py` implementing `DATA_MODEL.md §5` including the overlay.
5. `backend/app/domain/statement_rules.py` (regex list, versioned).
6. Tests: `test_derive_status.py` (one case per decision-table row, plus mismatch overlay, intent-switch precedence, staff closure), `test_statement_rules.py`, `test_migrations.py` (apply to `careflow_test`, apply twice is a no-op).
Files: `backend/migrations/`, `backend/app/{persistence,domain}/`, `backend/tests/`.
Acceptance: migrations apply cleanly to an empty schema; every decision-table row has a passing test; no
transcript input can yield `completed_*`.
Verification: `make migrate-test && make test`. Artifacts: none.
Stop: tests green. Defer: statement rules beyond the six kinds. Risk: Supabase connectivity. Fallback: Docker Postgres.

### Phase 2 — Flask tool boundary and deterministic simulators (1.75 h)
Objective: Vogent-shaped requests become persisted evidence with correct outcomes under fault profiles.
Why: R6–R9, R11, R12.
Dependencies: Phase 1.
Steps:
1. `app/api/auth.py`: token → organization; agent registration check; `X-Organization-Id` for `/api`.
2. `app/api/schemas.py`: pydantic models for the envelope and each function's params (bounds, phone, dates).
3. `app/services/idempotency.py`: key computation, insert-or-fetch semantics, in-flight handling.
4. `app/simulators/{scheduler,triage_line,callback_queue}.py`: pure functions of (params, fault profile) returning typed results, with attempt budgets; timeout simulated by sleeping past budget.
5. `app/services/actions.py`: the common pipeline (auth → call upsert → validate → idempotency → execute → persist → derive → log), with the retry rule (`DECISIONS.md` D8).
6. `app/api/vogent_functions.py`: four routes; `app/api/vogent_webhooks.py`: `dial.updated` (fetch dial with `services/vogent_client.py`), `dial.transcript`.
7. `app/api/evidence.py`: `/api/eval/dials`, `/api/calls`, `/api/calls/<id>`, `/api/calls/<id>/sync-dial`, `/api/calls/<id>/staff-actions`, evaluation-run endpoints; `/healthz`.
8. `app/observability/logging.py`: structlog JSON with allow-listed fields; request id middleware.
9. Tests: `test_functions_happy.py`, `test_fault_profiles.py`, `test_idempotency.py` (duplicate returns stored response, no second downstream row), `test_organization_scope.py` (wrong token 401, agent mismatch 403, cross-org call 404), `test_validation.py`, `test_webhooks_order.py` (transcript before function; late function after completion), `test_logging_redaction.py`.
Files: `backend/app/{api,services,simulators,observability}/`, tests.
Acceptance: all tests pass; a `transfer=fail, callback=fail` sequence yields `escalation_failed` with
two executions and one transfer session; duplicate `create_callback` creates exactly one queue row;
cross-organization lookup is 404; no log line contains a phone number in the redaction test.
Verification: `make test`. Artifacts: none.
Stop: acceptance met. Defer: `staff-actions` endpoint (cut #2), `sync-dial`. Risk: time. Fallback: drop webhooks' dial fetch to the runner (`sync-dial` becomes primary).

### Phase 3 — Local workflow verification by replay (0.50 h)
Objective: scenarios A–E proven against the running API without voice.
Why: Gate A; R27; the reviewer path.
Dependencies: Phase 2; scenario files (minimal versions) from Phase 5 step 1 pulled forward.
Steps:
1. `evals/scenarios/A–E.yaml` (fault profiles and expectations; caller turns may be placeholders until Phase 5).
2. `evals/fixtures/<scenario>/functions.json`: hand-written Vogent-shaped payloads (replaced by captured ones after Phase 4).
3. `evals/runner/replay.py`: register dial → POST payloads in order → synthetic `dial.updated` → fetch bundle → `metrics.py` → print table.
4. `make replay` and `make seed` (replay all scenarios into the demo organization).
Acceptance: A–E print expected derived statuses and required metrics pass; E shows `duplicate_of`.
Verification: `make replay`. Artifacts: none yet.
Stop: table matches `EVALUATION_PLAN.md §3`. Risk: none significant.

### Phase 4 — Vogent integration and both flow versions (1.50 h)
Objective: real browser calls hit the backend through the tunnel on V1 and V2.
Why: R3, R4, R6; assumptions A1–A6.
Dependencies: Gate A; `HUMAN_SETUP.md` C–D.
Steps:
1. `vogent/functions/*.json` (four) and `vogent/scripts/sync.py` (create/update functions with `apiPath`, print header instruction).
2. Manual browser call from the Vogent UI on a throwaway one-node flow calling `transfer_triage` with `transfer=fail` registered by hand → capture payload to `artifacts/spike/function_payload.json`; record A1, A3, A6 findings in `VOGENT_PLAN.md §2`.
3. Timeout/retry probe (A4): env flag makes the stub sleep 8 s once; count events.
4. `vogent/flows/v1.json`, `v2.json` per `VOGENT_PLAN.md §6–7`; `sync.py` creates both versioned prompts; `vogent/scripts/export.py` writes `vogent/export/`.
5. Manual smoke call per version for scenario C's fault profile; confirm A2 (branching) on V2 and the unconditional path on V1; save both dial IDs.
6. Replace hand-written fixtures with captured payloads; re-run `make replay`.
Acceptance: both versions exist with IDs in `.env`; V2 smoke call produces `callback_pending`; V1 smoke call produces `escalation_failed` with `promise_mismatch`; findings for A1–A4, A6 recorded.
Verification: dial IDs and evidence bundles saved in `artifacts/spike/`.
Stop: acceptance met. Defer: `report_disposition` (D6 revisit) if flow authoring overruns.
Risks: programmatic flow creation rejected; `Equal` semantics. Fallback: build in Flow Builder UI, export; freeform-node branching (A2 fallback).

### Phase 5 — Evaluation framework and synthetic caller harness (1.75 h)
Objective: `make eval VERSION=v2 SCENARIOS=A,B,C,D` runs real voice calls and writes artifacts and metrics.
Why: R14–R17, R24.
Dependencies: Gate B.
Steps:
1. Finish scenario files: caller turns, `end_when`, truthfulness sections.
2. `evals/caller_page/` (Vite + Web SDK; `window.caller.play`; getUserMedia override in an init script).
3. `evals/runner/tts.py` (`say` → WAV cache); `harness.py` (Playwright control, turn-taking, timeline).
4. `evals/runner/vogent_api.py` (create dial, get dial); `runner.py` (flow in `EVALUATION_PLAN.md §6`); `artifacts.py`; `metrics.py` complete.
5. First full voice run of scenario A on V2. **Gate at 1.25 h into the phase**: if no complete scripted call, switch to fallback ladder step 2, then 3, and record the decision in `INVESTIGATIONS.md`.
Acceptance: one scenario completes with `PASS`/`FAIL` (not `ERROR`) and a full artifact directory; metrics computed from the evidence bundle only.
Verification: `artifacts/v2/<run>/A_routine_scheduling/`.
Stop: acceptance met. Defer: `promise_before_evidence` metric, parallel contexts. Risks: audio injection, autoplay policy, STT on synthetic voice. Fallback: ladder.

### Phase 6 — V1 and V2 voice suites and investigation (1.75 h)
Objective: Experiment 1 complete with real evidence and one investigation.
Why: R18, R19.
Dependencies: Gate C.
Steps:
1. `make eval VERSION=v1` (A–D); save to `artifacts/v1/`.
2. `make eval VERSION=v2` (A–D); save to `artifacts/v2/`.
3. Investigate the first `FAIL`/`ERROR`/surprise per `EVALUATION_PLAN.md §10`; change one thing; re-run that scenario; write `INV-1`.
4. Write the results table and the improved/unchanged/regressed/surprised/cannot-establish paragraphs into `SUBMISSION.md §6` draft.
Acceptance: 8 voice cases with dial IDs; `INVESTIGATIONS.md` has one entry with before/after IDs.
Stop: acceptance met. Defer: re-runs beyond one per `ERROR`. Risk: cost/time per call. Fallback: manual-mic runs.

### Phase 7 — Evaluation efficiency experiment (1.00 h)
Objective: Experiment 2 measured on frozen V2.
Why: R20, R21.
Dependencies: Gate D.
Steps:
1. `evals/runner/structural.py` (rules in `EVALUATION_PLAN.md §9`); run on V1 and V2 exports.
2. `make eval STRATEGY=naive_voice VERSION=v2` → `artifacts/efficiency/baseline/<run>/run_summary.json`.
3. `make eval STRATEGY=optimized VERSION=v2` (cold cache) → `artifacts/efficiency/optimized/<run>/`.
4. Check the Billing tab; write `artifacts/efficiency/billing.md` with labels.
5. Savings table, coverage-loss list, disagreement table → `SUBMISSION.md §6`.
Acceptance: both summaries contain wall-clock, per-case and total seconds and dollars with `cost_label`; report states savings or honestly reports none.
Stop: report written. Defer: parallel contexts if `RATE_LIMITED`. Risk: baseline flakiness inflates time (report as measured).

### Phase 8 — Staff investigation UI (1.50 h)
Objective: `/calls` and `/calls/[id]` on persisted data, completing the required trace.
Why: R13, R28.
Dependencies: Phase 2 contract; data from Phases 3–7.
Steps:
1. `npx create-next-app frontend --ts --app`; `lib/api.ts` (server-side fetch with `BACKEND_URL`, `X-Organization-Id`).
2. `app/calls/page.tsx` list per `UI_PLAN.md`; `app/calls/[id]/page.tsx` evidence view; `components/PromiseVsEvidence.tsx`, `Timeline.tsx`.
3. Staff action buttons (server actions) if R28 kept.
4. Screenshot scenario C and D detail pages → `artifacts/v2/<run>/ui_*.png`.
Acceptance: attention list shows D above C; detail view shows promise vs. evidence, reason, next step, IDs; screenshot saved.
Stop: screenshots saved. Defer: staff buttons, styling. Risk: time. Fallback: single page with both views.

### Phase 9 — Async worker and Terraform (0.75 h)
Objective: queue → worker → result with DLQ demonstrated locally; IaC validates.
Why: R22.
Dependencies: Phase 3 (replay mode).
Steps:
1. `worker/bootstrap.py` (queues + redrive on `moto` server), `worker/main.py`, `worker/enqueue.py`, `worker/dlq_inspect.py`.
2. Run success job (A) and poison job; save logs and DLQ dump to `artifacts/worker/`.
3. `infra/terraform/{main,sqs,ecs,iam,ssm,logs,variables,outputs}.tf`; `terraform validate` output saved.
Acceptance: run rows `completed` and `failed`; DLQ contains the poison message with `job_id`; `terraform validate` succeeds.
Stop: evidence saved. Defer: alarm resource, ECS service (keep task definition). Risk: `moto` redrive fidelity. Fallback: ElasticMQ in Docker.

### Phase 10 — Submission consolidation (1.00 h)
Objective: `SUBMISSION.md`, `MANAGER_UPDATE.md`, `README.md` run path, video.
Why: R2, R26; deliverables 1–11.
Steps:
1. `SUBMISSION.md` sections 1–11 from the checklist; links to artifacts and IDs.
2. `docs/MANAGER_UPDATE.md`: what staff can trust, what remains manual, what next — written from actual results.
3. `README.md` two-minute path (`make setup migrate seed api ui`); `make secret-scan`.
   The candidate finalises `TIME_LOG.md` themselves; Claude does not touch it.
4. Record the ≤ 8-minute walkthrough (scenario C trace, V1 vs V2 table, efficiency table, worker DLQ).
Acceptance: `SUBMISSION_CHECKLIST.md` fully ticked with links; time log ≤ 16 h.

## 6. Scope removed in this review

Stretch scenarios F (unverified transfer) and G (off-policy request) → deferred (edge handling remains
in the backend and tests). Organization switcher UI → removed; isolation proven by tests. Result cache
with invalidation logic → reduced to a documented skip rule. Alembic and SQLAlchemy → removed (D5).
ElasticMQ/Docker → replaced by `moto` server (Docker optional). Live AWS → not planned. LLM judge → deferred.

## 7. Cut order if the buffer is consumed

1. Phase 9 alarm and ECS service resources (keep queue, DLQ, IAM, SSM, logs, task definition).
2. Staff action buttons (R28).
3. `promise_before_evidence` metric and parallel voice contexts.
4. Phase 9 entirely (document design only) — only if Phases 6–7 are at risk.
5. UI styling of any kind.
Never cut: voice runs for A–D on both versions, scenario D, the investigation, the two measurements.
