# Decision Log

Only decisions that reflect judgment. Format: context · options · decision · rationale · tradeoff · revisit when.

### D1 — Flask derives status; Vogent and the UI never do
Context: the customer bug is a status derived from the agent's words. Options: extractor/`aiResult` in
Vogent; UI-side logic; backend pure function. Decision: one pure function in the backend over persisted
rows. Rationale: testable, single source, identical for UI and evaluator. Tradeoff: the UI cannot show
anything the backend has not derived. Revisit: never for this problem.

### D2 — Evidence modeled as generalized `action_executions` plus three explicit downstream tables
Options: one table with a `kind` column and JSON state; per-action tables only; both. Decision: both.
Rationale: uniform execution evidence (idempotency, attempts, outcome) and directly inspectable
"what does the callback queue contain" state; a failed callback creation correctly leaves no queue row.
Tradeoff: three small tables to maintain. Revisit: if a fourth simulated system appears.

### D3 — Agent promise captured from transcript rules and a `report_disposition` function
Options: transcript only; disposition only; LLM classifier. Decision: both deterministic sources, no LLM.
Rationale: the transcript is the authoritative record of what was said; the disposition is the structured
claim real systems use and the exact thing the customer's status was built on. Tradeoff: regexes miss
unanticipated phrasing (informational only). Revisit: if phrasing variance makes `promise_mismatch` noisy.

### D4 — Supabase used only as managed PostgreSQL
Options: local Docker Postgres; Supabase; SQLite. Decision: Supabase (plain `DATABASE_URL`), Docker
compose kept for reviewers. Rationale: no daemon to babysit, reachable by a worker from anywhere, real
Postgres semantics. Tradeoff: network latency on every request (fine at this scale); a second schema for
tests. Revisit: if latency affects the 6 s function budget.

### D5 — psycopg 3 with plain SQL migrations; no ORM, no Alembic
Options: SQLAlchemy ORM + Alembic; SQLAlchemy Core; psycopg + SQL files. Decision: psycopg + numbered
SQL files. Rationale: ten tables, explicit constraints, queries a reviewer can read; migration tooling
adds setup time without value in a 16-hour project. Tradeoff: hand-written mapping code. Revisit: if the
schema grows past what SQL files keep readable.

### D6 — Four functions including `report_disposition`
Options: three functions and infer intent/disposition from the transcript. Decision: keep the fourth.
Rationale: gives `agent_classified_intent` without an LLM, and makes V1's "resolved" claim a structured
row the dashboard can contrast with evidence. Tradeoff: one more node per branch in both flows.
Revisit: if flow authoring time overruns in Phase 4 (drop it; rely on transcript rules).

### D7 — Business failures are HTTP 200 with a `status` field
Rationale: the flow must branch on `failed`; a 5xx reaches the model as an opaque error and removes the
agent's ability to disclose truthfully. Tradeoff: monitoring must read `status`, not HTTP codes. Revisit: no.

### D8 — Transfer never retried; callback retried once on timeout
Rationale: a retried transfer rings a clinical line twice; policy prescribes the callback fallback
instead. The callback queue is idempotent, so one retry is safe. Tradeoff: a transient transfer blip
becomes a callback. Revisit: with real telephony semantics.

### D9 — Real voice runs remain mandatory despite deterministic preflight and replay
Rationale: replay proves the backend and a recorded agent; only voice proves STT → flow → function
invocation with real timing. The optimized strategy keeps C and D on voice for exactly this reason.
Tradeoff: cost and flakiness. Revisit: never within this assignment.

### D10 — Organization scoping by shared-secret tokens; no user authentication
Rationale: the assignment requires isolation, not an identity product; tokens per organization plus
`organization_id` on every query and cross-organization tests demonstrate the boundary. Tradeoff: no
audit of *who* on staff acted (free-text actor). Revisit: first production deployment (see `RISKS.md`).

### D11 — V1 and V2 are two versioned prompts of one agent, pinned per dial
Rationale: identical functions and context isolate the flow change; `versionedModelId` makes every run
attributable; the efficiency experiment freezes one version trivially. Tradeoff: version IDs are
workspace-specific and live in `.env`/export, not in code. Revisit: no.

### D12 — Async path demonstrated with a local SQS emulator and Terraform, not a live deployment
Rationale: the assignment makes live AWS optional; the judgment being evaluated is the shape (queue →
worker → result, DLQ, correlation, least privilege, teardown). Tradeoff: `terraform validate` only.
Revisit: if a safe sandbox and spare hours exist after Phase 10.

### D13 — Scenarios A and B move to replay in the optimized strategy; C and D stay on voice
Rationale: risk-based selection: their flow paths contain no failure branch and their backend behavior is
fully exercised by replay; the high-risk path must keep real voice. Tradeoff: documented coverage loss on
the scheduling path (STT, invocation). Revisit: if the disagreement table shows replay and voice disagreeing.
