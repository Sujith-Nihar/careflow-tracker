# API Design (Flask)

Owner of: every HTTP contract the backend exposes. Three surfaces in one app: Vogent-facing
(`/vogent/*`), evidence/evaluation (`/api/*`), health. No REST ceremony beyond what the UI and runner need.

## 1. Conventions

| Concern | Rule |
|---------|------|
| Organization | Vogent routes: `X-CareFlow-Token` header → `organizations.function_token_hash`. Webhooks: token in the URL path (Vogent webhook headers are not configurable per dial). `/api/*`: `X-Organization-Id` header, validated to exist. No user identity; see `RISKS.md`. |
| Correlation | Every response carries `X-Request-Id`. Vogent routes log `dial_id`; `/api` routes log `call_id` where present. |
| Business outcomes | Returned as **HTTP 200 with a `status` field**. The flow must be able to branch on a failed transfer; a 5xx would surface to the model as an opaque error. |
| Errors | 401 bad token · 403 organization/agent mismatch · 400 malformed envelope · 404 unknown call in this organization · 422 unknown scenario (eval). Body `{error, request_id}`. Never a stack trace. |
| Validation | All Vogent `params` are strings from an LLM. Bounded lengths (≤ 200 chars, `reason` ≤ 500), phone → E.164 or `invalid_input`, dates parsed with an explicit format list or `invalid_input`, enums matched case-insensitively. Unknown keys ignored, never persisted. |
| Idempotency | `sha256(dial_id + function + canonical_json(params))`. Duplicate → return the stored `response_payload`, log `duplicate=true`, insert a `vogent_events` row, set `duplicate_of_id`. In-flight duplicate (unique violation while the first is `requested`) → `{status: "unverified"}`. |
| Timeouts | Simulator attempt budget 2 s; endpoint budget 6 s; on budget exhaustion outcome `unverified`. |
| Duplicate evidence | A repeat is stored as its own execution linked by `duplicate_of_id`, so the vendor's retry stays visible while exactly one downstream record exists. This is de-duplication for identical params on one dial, not an exactly-once guarantee. |
| Schema pinning | `search_path` is set per pooled connection, not via the `options` startup parameter, because connection poolers do not forward `options`. |
| Logging | Events from `ARCHITECTURE.md §9`; never `params` values, phone, names, transcript. |

## 2. Endpoint summary

| Method | Path | Caller | Purpose |
|--------|------|--------|---------|
| POST | `/vogent/functions/schedule_appointment` | Vogent | Book a routine appointment (simulated) |
| POST | `/vogent/functions/transfer_triage` | Vogent | Attempt live triage transfer (simulated) |
| POST | `/vogent/functions/create_callback` | Vogent | Create a callback request (simulated) |
| POST | `/vogent/functions/report_disposition` | Vogent | Record the agent's own claim of what it told the caller |
| POST | `/vogent/webhooks/<webhook_token>` | Vogent | `dial.updated`, `dial.transcript` |
| POST | `/api/eval/dials` | Runner | Register `dial_id` + scenario + fault profile before the call |
| POST | `/api/calls/<call_id>/sync-dial` | Runner | Force fetch of the Vogent dial record (fallback when the webhook is late) |
| GET | `/api/calls?requires_staff_action=true&limit=` | UI | Attention list, sorted by severity then time |
| GET | `/api/calls/by-dial/<dial_id>` | UI, runner | Resolve a Vogent dial to a call id |
| GET | `/api/calls/<call_id>` | UI, runner | Full evidence bundle + derived status |
| POST | `/api/calls/<call_id>/staff-actions` | UI | `callback_completed` or `reviewed` |
| POST | `/api/evaluation-runs` · PATCH `/api/evaluation-runs/<id>` · POST `/api/evaluation-runs/<id>/cases` | Runner, worker | Persist run and case results |
| GET | `/api/evaluation-runs/<id>` | UI (optional), reviewer | Run summary and cases |
| GET | `/healthz` | anyone | DB connectivity, git SHA |

## 3. Vogent function endpoints

Request envelope (from Vogent, verified in Phase 4): `{ "dial_id": "...", "dial": {...}, "params": {...} }`.
Handling, identical for all four: authenticate → find or create `calls` row for `dial_id` (lifecycle
`in_progress`) → verify `dial.agent.id` registration → attach `fault_profiles` if registered → validate
`params` → compute idempotency key → insert `action_executions(requested)` → run simulator → persist
downstream row → update execution → respond.

The request is persisted **before** the simulated system is touched and the downstream record **before**
the response is returned, so a mid-flight failure leaves an attempt with no result rather than a silent
gap. Status is **not** derived on this path: the caller is on the phone, the response body carries no
status, and derivation is a pure function of already-committed rows, so it is computed on read instead.

### schedule_appointment
params: `patient_ref` (string ≤ 64), `preferred_date` (string), `reason` (string ≤ 500, routine only).
response: `{status: booked|unavailable|invalid_input|unverified, appointment_id?, slot_iso?, agent_message}`.
`agent_message` is short, factual text the flow may read back ("Booked for Tuesday the 24th at 10 AM").

### transfer_triage
params: `patient_ref`, `concern_summary` (≤ 500), `callback_phone` (string).
response: `{status: connected|failed|unverified, transfer_session_id?, failure_reason?, agent_message}`.
Never retried by the backend.

### create_callback
params: `patient_ref`, `callback_phone`, `priority` (`urgent` | `normal`), `reason_code`
(`transfer_failed` | `unsupported_request` | `caller_requested`).
response: `{status: created|failed|invalid_input|unverified, callback_id?, priority, agent_message}`.
One retry on `timeout`; the queue simulator is idempotent on the execution id.

### report_disposition
params: `category` (`routine_scheduling` | `post_operative_concern` | `other`),
`disposition` (`scheduled` | `transferred` | `callback_pending` | `escalation_failed` | `unresolved` | `resolved`),
`summary` (≤ 300).
response: `{status: recorded}`. Persists an `agent_statements(kind=reported_disposition, source=function_param)`
row and sets `calls.agent_classified_intent`. **This is a claim, never an input to completion.**

## 4. Webhooks

`POST /vogent/webhooks/<webhook_token>` with `{event, payload}`.
`dial.updated` with `status` terminal → set lifecycle `ended`, then fetch `GET /dials/{id}` with the
workspace key (`connected_seconds = aiDurationSeconds`, `started_at`, `ended_at`, `system_result_type`,
`versioned_prompt_id`, `transcript`), run transcript statement rules, recompute status.
`dial.transcript` → store transcript, run statement rules. Dedupe key `sha256(event, dial_id, payload)`.
Out-of-order or late events are accepted; derivation is a pure function of the rows.

Transcript statement rules (deterministic regex over `speaker = AI` segments, listed in
`backend/app/domain/statement_rules.py`): e.g. `connecting you|transferring you` → `promised_transfer`;
`will call you back|callback` → `promised_callback`; `booked|scheduled for` → `promised_appointment`;
`transfer (did not|didn't|could not) (complete|go through)` → `disclosed_transfer_failed`. Rules are
versioned with the scenario suite and tested on fixtures; they capture *what was said*, nothing more.

## 5. Evidence bundle (`GET /api/calls/<call_id>`)

```json
{
  "call": {"id": "...", "dial_id": "...", "versioned_prompt_id": "...", "lifecycle": "ended", "connected_seconds": 71, "scenario_id": "C_postop_transfer_fail_callback", "evaluation_run_id": "..."},
  "intent": {"agent_classified": "post_operative_concern", "true_intent": "post_operative_concern"},
  "agent_statements": [{"kind": "promised_transfer", "source": "transcript_rule", "evidence_text": "...", "observed_at": "..."}],
  "action_executions": [{"id": "...", "kind": "transfer_triage", "outcome": "failed", "attempts": [...], "request_payload": {...}, "response_payload": {...}, "requested_at": "...", "completed_at": "..."}],
  "downstream": {"appointments": [], "transfer_sessions": [{"status": "failed", "failure_reason": "no_answer"}], "callback_requests": [{"status": "created", "priority": "urgent"}]},
  "staff_actions": [],
  "derived": {"status": "callback_pending", "severity": 2, "requires_staff_action": true,
              "reason": "Transfer to triage failed (no answer); urgent callback created and not yet completed.",
              "next_step": "Call the patient back at the recorded number.", "promise_mismatch": false,
              "evidence_refs": {"transfer_session_id": "...", "callback_id": "..."}},
  "transcript": {"authoritative": false, "segments": [...]}
}
```

The evaluator and the UI both consume exactly this document.
