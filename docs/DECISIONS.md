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

### D12 — Async path designed but not built
Context: the plan was a local SQS emulator plus Terraform. Options: build it, cut it, or fake it.
Decision: **cut it, and say so.** The voice work overran and something had to give. Rationale: the brief
marks live AWS optional, and real voice evidence on the high-risk path is weighted far more heavily
than a queue demo. Tradeoff: the one core expectation with no running code; `docs/ASYNC_INFRA_PLAN.md`
is a design, not a demonstration. Revisit: first thing with any further time.

### D13 — Scenarios A and B move to replay in the optimized strategy; C and D stay on voice
Rationale: risk-based selection: their flow paths contain no failure branch and their backend behavior is
fully exercised by replay; the high-risk path must keep real voice. Tradeoff: documented coverage loss on
the scheduling path (STT, invocation). Revisit: if the disagreement table shows replay and voice disagreeing.

### D14 — The escalation decision lives in the backend, not in the conversation flow
Context: V2's original design branched on the transfer result with an outcome-conditioned edge. Isolated
probes showed Vogent function nodes never match `equal` or `in` rules against their own result, with or
without a field name, although the value *is* readable downstream as `{{node.fn.status}}`
(`INVESTIGATIONS.md` INV-4). Options: (a) push harder on prompt wording so the model reliably decides to
escalate; (b) restructure the graph around the limitation; (c) move the decision out of the conversation
entirely. Decision: **(c)**. The flow now always requests a callback after a transfer attempt, and the
backend consults the persisted transfer sessions to decide whether one is warranted, returning
`not_needed` when a transfer actually connected. Rationale: the guarantee that a post-operative caller
is not abandoned should not depend on a language model reading a string correctly. Escalation is now a
property of persisted state, and the flow cannot be talked out of it because it no longer makes the
choice. Tradeoff: one extra function round trip per post-operative call, and the graph no longer encodes
the policy branch, so the structural check had to be rewritten to test what the flow *says* rather than
what it *routes*. Revisit: if Vogent adds working outcome-conditioned edges, the branch could move back —
but the backend version is safer and I would keep it.

### D15 — A fourth action outcome, `not_applicable`
Context: D14 means `create_callback` is called on every post-operative call, including ones where the
transfer connected. Options: record it as `succeeded` (false: nothing was created), as `failed` (false:
nothing went wrong), or add a state. Decision: add `not_applicable` — asked for, correctly declined.
Rationale: collapsing it into either existing state would corrupt the metric that no `succeeded` action
lacks a downstream record, which is one of the suite's strongest assertions. Tradeoff: one more state in
the vocabulary and a migration. Revisit: no.

### D16 — The browser transcript is the primary record of what was said
Context: `GET /dials/{id}` truncates the agent's final utterance. Scenario D failed its disclosure check
three times on calls where the agent had said exactly the right thing; the Web SDK's live transcript held
the full sentence while the stored dial record kept four words of it. Decision: the evaluation runner
feeds the browser transcript to the backend, which re-scores statements from it. Rationale: scoring
truthfulness from a record known to be incomplete produces false failures on correct calls, which is
worse than no check. Tradeoff: the richer record exists only when the harness captured it; a call
observed only through webhooks still relies on the vendor's copy. This changes no action state —
transcripts remain evidence of speech, never of action. Revisit: if the vendor's transcript becomes complete.

### D17 — Evaluation runs are persisted, not only written to disk
Context: run results lived only as JSON artifacts, while `evaluation_runs` and `evaluation_cases` sat
unused in the schema. Options: delete the tables, or write to them. Decision: write to them, with the
runner supplying the run id so the directory on disk and the row in the database are the same run.
Rationale: a result should be queryable next to the calls it produced, and an async worker needs
somewhere to report to. Dead tables alongside documented-but-missing endpoints is how a codebase starts
lying about itself. Tradeoff: three more endpoints to maintain. Revisit: no.
