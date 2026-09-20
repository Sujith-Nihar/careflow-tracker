# Requirements Matrix

Source: `ASSIGNMENT.md`. Priority: **MUST** (required outcome / core expectation), **SHOULD** (core
expectation detail), **MAY** (additional work). Status set from something run or read, not from
intent; last reconciled against the finished system on 2026-09-19.

| ID | Requirement | Pri | Component | Phase | Verification | Evidence | Status |
|----|-------------|-----|-----------|-------|--------------|----------|--------|
| R1 | Triage plan before implementation (failure model, verify-first, smallest outcome, priorities, plan-changing evidence, questions) | MUST | docs | 0 | review | `PROJECT_PLAN.md §1` | done |
| R2 | Plain-language practice-manager update | MUST | docs | 10 | review | `MANAGER_UPDATE.md` | done |
| R3 | Flow-based agent in the isolated Vogent workspace distinguishing routine / post-op / other | MUST | vogent | 4 | manual smoke call | `vogent/export/`, agent + version IDs | done |
| R4 | Flow export or complete reproducible description with version | MUST | vogent | 4, 10 | file present | `vogent/export/`, `VOGENT_PLAN.md §6–7` | done |
| R5 | Completion determinable from evidence, not transcript | MUST | backend domain | 1 | unit tests per scenario | `backend/tests/test_derive_status.py` | done |
| R6 | Handle Vogent-style function requests | MUST | backend api | 2 | replay + real call | captured payload in `artifacts/spike/` | done |
| R7 | Idempotency / duplicate events | SHOULD | backend | 2 | test + scenario E | `test_api_idempotency.py`, scenario E replay | done |
| R8 | Organization isolation | SHOULD | backend | 1–2 | cross-org tests | `test_api_isolation.py` | done |
| R9 | Timeouts, retries, failed downstream actions | SHOULD | backend simulators | 2 | fault-profile tests | `test_api_scenarios.py` fault profiles | done |
| R10 | Truthful status derivation | MUST | backend domain | 1 | decision-table tests | `DATA_MODEL.md §5`, tests | done |
| R11 | Validation of string payloads | SHOULD | backend api | 2 | validation tests | `test_api_validation.py` | done |
| R12 | Logs useful without sensitive data | SHOULD | backend observability | 2 | log fixture test | `test_logging_redaction.py` | done |
| R13 | Staff UI: needs action, promised, actual, why, next step, on persisted data | MUST | frontend | 8 | screenshot of scenario C detail | `SUBMISSION.md §2` | done |
| R14 | Real Vogent browser voice evaluations with synthetic audio (no telephony) | MUST | evals, vogent | 5–7 | dial records | `artifacts/v1/`, `artifacts/v2/` | done |
| R15 | Scenarios: routine, post-op transfer, failed transfer + callback, one subtle failure | MUST | evals | 5 | files + runs | `evals/scenarios/A–D` | done |
| R16 | Each case defines goal, expected behavior, authoritative evidence, pass/fail | MUST | evals | 5 | schema check | `EVALUATION_PLAN.md §2` | done |
| R17 | ≥ 1 deterministic function/state metric | MUST | evals | 5 | metrics code | `metrics.py` | done |
| R18 | Compare two agent behaviors with real voice results for both | MUST | evals, vogent | 6–7 | results table | `SUBMISSION.md §6` | done |
| R19 | Investigate one failure or surprise; record whether evidence changed the implementation | MUST | evals | 6 | log entry | `INVESTIGATIONS.md` | done |
| R20 | Naive sequential full-voice suite measured: wall-clock, connected seconds, dollars; raw + pricing evidence; billed vs estimate | MUST | evals | 7 | `run_summary.json` | `artifacts/efficiency/baseline/` | done |
| R21 | Improved strategy on same scenarios and frozen version; measured savings in time and dollars; coverage and disagreement analysis; high-risk path on voice | MUST | evals | 7 | `run_summary.json` + report | `artifacts/efficiency/optimized/`, `SUBMISSION.md §6` | done |
| R22 | Async path design + IaC; local demo of success, poisoned job → DLQ, log correlation, least privilege, deploy/teardown | MUST | worker, infra | 9 | local run + `terraform validate` | `artifacts/worker/`, `infra/terraform/` | done |
| R23 | Persisted data (PostgreSQL) | MUST | backend | 1 | migrations apply | `backend/migrations/` | done |
| R24 | Save dial IDs, agent/version IDs, timestamps, traces, function results, final state | MUST | evals | 5–7 | artifact layout | `EVALUATION_PLAN.md §7` | done |
| R25 | Never publish workspace credentials | MUST | repo | all | secret scan | `make secret-scan` output | done |
| R26 | AI-usage account: delegated, verified, rejected, own decision | MUST | docs | 10 | review | `SUBMISSION.md §10` | done |
| R26b | Time log ≤ 16 h, coarse by workstream | MUST | docs | 10 | file | `TIME_LOG.md`, 15.9 h across 12 workstreams | done |
| R27 | Deterministic replay; version scenarios/flows | MAY | evals | 3, 5 | `make replay` | fixtures | done |
| R28 | Human review / override (mark callback completed) | MAY | backend, frontend | 2, 8 | UI action | `staff_actions` | done |
| R29 | Judgment-based evaluator with rubric | MAY | — | — | — | not attempted, declared in `SUBMISSION.md §5` | deferred |
| R30 | Organization tokens for both external surfaces | MAY | backend api | 2 | isolation tests | `api/auth.py`, `test_api_isolation.py` | done |
| R31 | Continuous integration | MAY | repo | 10 | workflow run | `.github/workflows/ci.yml` | done |
| R32 | User authentication, accessibility audit, live AWS deploy | MAY | — | — | — | out of scope, stated in `SUBMISSION.md §5` and `RISKS.md` | deferred |
| R33 | Single-take walkthrough video ≤ 8 min | MUST | docs | 10 | link in `SUBMISSION.md` | linked at the top of `SUBMISSION.md` | done |
