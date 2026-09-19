# Security, Privacy, Reliability, and Production Risks

Classification: **M** mitigated in the take-home · **P** partially mitigated · **D** intentionally deferred.
This is a synthetic-data exercise. No claim of HIPAA compliance or production security is made.

## Security and privacy

| Risk | Class | Handling in take-home | Production requirement |
|------|-------|-----------------------|------------------------|
| Vogent/DB/ngrok credentials leak via repo, logs, screenshots | M | `.env` git-ignored; `.env.example` has names only; logs never include tokens; screenshots cropped | secrets manager, rotation, pre-commit scanning |
| Frontend leaks backend secret | M | server-side fetch only; no `NEXT_PUBLIC_*` secrets | same, plus CSP |
| Spoofed function/webhook requests | P | per-organization shared-secret header; webhook token in path; agent-to-organization registration check | request signing/mTLS from vendor, IP allow-list, replay window |
| Cross-organization data exposure | M | `organization_id` on every table and query; token-resolved org; tests assert 404 across orgs | row-level security, per-org DB roles, audit |
| Staff identity and authorization | D | free-text `actor`, no login (`DECISIONS.md` D10) | SSO, RBAC, audit trail |
| Sensitive data in logs | M | allow-list of log fields; payloads persisted, not logged | log redaction review, retention limits |
| PHI at rest / in transit | P | TLS to Supabase and Vogent; synthetic data only | encryption key management, BAA with vendors, retention/deletion policy |
| Accidental real data | M | synthetic identifiers (`PT-SYN-*`, 555 numbers); no telephony; isolated workspace | environment separation, data classification |
| Malformed or hostile LLM-produced strings | M | bounded, typed validation; unknown keys dropped; `invalid_input` not 500 | fuzzing, schema registry |

## Reliability

| Risk | Class | Handling | Production requirement |
|------|-------|----------|------------------------|
| Duplicate function invocations | M | idempotency key + unique constraint; stored response returned | same, plus vendor request IDs |
| Late, missing, or out-of-order webhooks | M | append-only events; order-independent derivation; runner fallback `sync-dial`; `ended_unconfirmed` after staleness | reconciliation job against vendor API |
| Downstream timeouts | M | attempt budgets; `unverified` outcome; fallback path | circuit breakers, alerting |
| Backend unreachable during a call | P | flow's Always-branch discloses; absence of evidence → `no_action_recorded` | HA deployment, vendor-side retry configuration |
| Function timeout unknown | P | measured in Phase 4; 6 s budget | contractual SLA with vendor |
| Vogent rate limits / concurrency | P | sequential fallback | quota management |
| Harness flakiness (STT, timing) | P | `ERROR` class separate from `FAIL`; one re-run allowed for `ERROR`; artifacts kept | larger suites, statistical treatment |

## Product and operational

| Risk | Class | Handling | Production requirement |
|------|-------|----------|------------------------|
| Staff over-trust "completed" statuses | P | completion defined by downstream evidence; UI labels sources; transcript marked non-authoritative | training, periodic audits |
| Callback SLA not tracked | D | `created_at` shown; no timers | SLA timers, paging |
| Policy drift (flow edited without re-evaluation) | P | structural preflight; versions pinned; export in repo | release gating on eval suite |
| Sample size misinterpreted | M | stated in `EVALUATION_PLAN.md §11` and the submission | production monitoring of promise-mismatch rate |
