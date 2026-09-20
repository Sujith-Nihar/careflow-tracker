# Time Log (active hours, cap 16h)

Coarse, by workstream. Local time.

| # | Date       | Workstream                                                        | Hours | Notes |
|---|------------|-------------------------------------------------------------------|-------|-------|
| 1 | 2026-09-18 | Requirement understanding, infra options, service exploration (Vogent, Supabase, ngrok, AWS shape) | 1.5   | reading the brief and Vogent docs, checking accounts and tooling |
| 2 | 2026-09-18 | Planning and architecture (triage plan, design review, docs set)  | 2.0   | docs/ARCHITECTURE, DATA_MODEL, API_DESIGN, VOGENT_PLAN, EVALUATION_PLAN, PROJECT_PLAN, matrix, decisions, risks |
| 3 | 2026-09-19 | Phase 0 tooling and Phase 1 domain layer (types, derivation, statement rules, tests, schema) | 1.5 | 55 tests, 100% derivation coverage |
| 4 | 2026-09-19 | Phase 2 Flask boundary: simulators, idempotency, org scoping, validation, logs, evidence API | 2.0 | 86 tests against real PostgreSQL |
| 5 | 2026-09-19 | Phase 3 scenarios, metrics, replay runner | 0.5 | five scenario files, deterministic metric set |
| 6 | 2026-09-19 | Phase 4 Vogent functions, V1 and V2 flows, browser voice harness | 3.5 | the long pole: 78 calls across 24 published versions; INV-1 to INV-7 |
| 7 | 2026-09-19 | Phase 5-6 evaluation runs, metrics, V1 vs V2 comparison | 1.25 | runs 278133e5 (V1 2/4) and febdde6d (V2 4/4) |
| 8 | 2026-09-19 | Phase 7 efficiency experiment, naive vs optimised | 0.75 | run 88643fe6; 183s to 156s, $0.1770 to $0.0885 |
| 9 | 2026-09-19 | Phase 8 staff dashboard on persisted evidence | 1.25 | attention list and call detail, plain-language columns |
| 10 | 2026-09-19 | Phase 9 async worker, dead-letter queue demo, Terraform | 0.75 | artifacts/worker/, terraform validate |
| 11 | 2026-09-20 | Phase 10 hardening, documentation, submission write-up | 0.5 | 98 tests, lint and secret-scan gates, SUBMISSION.md |
| 12 | 2026-09-20 | Walkthrough video and final links | 0.4 | single take, no editing |

**Total: 15.9 h** (cap 16 h)
