# Vogent Plan

Owner of: what we know about Vogent, what we assume, what needs a human in the workspace, and how the
agent, its two versions, and the four functions are represented and reproduced.

## 1. Verified from official documentation (docs.vogent.ai, read 2026-09-18)

| Fact | Source path |
|------|-------------|
| Agent versions are **versioned prompts**: `POST/GET /agents/{agentId}/versioned_prompts`; `agentType` `CUSTOM_FLOW`; `flowDefinition = {nodes[], globalContext, openingLineType}`; each node has `id`, `name`, `type`, `transitionRules`, `nodeData` | `/api-reference/create-versioned-prompt.md`, `/api-reference/list-versioned-prompts.md` |
| Node types `question` (`questionType`, `options`), `freeform` (`prompt`), `function_call` (`functionId`, `inputs[]`, `outputs[]` with `nullable`) | `/developers/schemas` |
| Transitions are ordered rules with a **Variable** (a past node's output) and condition **Always / Equal (semantic) / In**; references `{{node.<id>.<field>}}` | `/platform-overview/agents/model/flow-builder`, `/developers/schemas` |
| Functions: `POST /functions` with `type: api`, `apiPath`, `headers[]`, `inputJsonSchema`, `lifecycleMessages{started[], waiting[], awaitSpeech}` | `/api-reference/create-a-function.md` |
| Function invocation is a POST with body `{dial_id, dial: {...}, params: {...}}` | `/developers/webhooks/function-call.md` |
| `POST /dials` accepts `callAgentId`, `browserCall`, `versionedModelId`, `callAgentInput`, `webhookUrl`, `timeoutMinutes`, `idempotencyKey`; returns `dialToken`, `sessionId`, `dialId` | `/api-reference/create-a-new-dial.md` |
| `GET /dials/{id}` returns `status`, `systemResultType`, `durationSeconds`, `aiDurationSeconds`, `startedAt`, `endedAt`, `transcript[]`, `agent{id}`, `versionedPromptId`, `inputs`; **no cost field** | `/api-reference/get-dial.md` |
| Webhooks `dial.updated {dial_session_id, dial_id, status}` and `dial.transcript {dial_id, transcript[{text, speaker: AI|HUMAN}]}` | `/developers/webhooks/*.md` |
| Web SDK `@vogent/vogent-web-client`: `new VogentCall({sessionId, dialId, token})`, `start()`, `connectAudio()` (microphone), `monitorTranscript()`, `on('status')`, `hangup()` | `/sdk/web-sdk` |
| Billing: metered per second; standard voices $0.09/min ($0.0015/s), premium $0.14/min; usage in the Billing tab; no usage API documented | `/platform-overview/billing` |

## 2a. Corrections found by building against the live API (2026-09-19)

| Documented | Actually accepted | Where it bit |
|------------|-------------------|--------------|
| node `type: "function_call"` | **`"function"`** | `POST /agents/{id}/versioned_prompts` returns `500 unknown node type: function_call`. `freeform` and `question` are as documented. |
| `inboundWebhookResponse` described as a string | **boolean** | `POST /agents` rejects a string with a schema error |
| Model list endpoint not in the docs index | `GET /models` | needed for the required `aiModelId`; this workspace exposes flow-tuned models (`GPT-5.4 Flow`) |
| Voices endpoint returns `voices`, not `data` | `GET /voices` → `{voices: [...]}` | pagination key differs from every other list endpoint |
| Function `path` field | request field is **`apiPath`**; `headers` are `[{key, value}]`; `inputJsonSchema` is a **JSON string**, not an object | `POST /functions` |
| Question node output referenced as `{{node.<id>.output}}` | the field is **`answer`** (`outputSchema` confirms it) | every scheduling and concern template silently referenced a missing field |
| `aiOpen` documented as deprecated | accepted and **ignored**; stays `false` | it is not the lever for who speaks first |
| Which node types may open a call | **any node type opens a call fine.** The silence had nothing to do with node type (see INV-3). | two runs misdiagnosed before the real cause was isolated |
| Freeform node progression | a freeform node **stays put unless its prompt states when to move on**. The docs say progression "depends on conditions stated in the node's prompt"; in practice an instruction like "say it once, then move on immediately" is required or the node loops. | the agent repeated "I can help with that. Please hold." until the call timed out |
| Dial record transcript is the complete record | **it truncates the agent's final utterance.** The Web SDK's live transcript held the full closing sentence while `GET /dials/{id}` stored only its first four words. | scenario D failed its disclosure check three times on a call where the agent said exactly the right thing |
| `dial.created` webhook | exists, not in the documented event list | arrives before the runner registers the dial, which exposed a create race |
| `modelOptionValues` offered by the model metadata | **temperature below the default makes the agent mute**; accepted with 200, no error anywhere | four silent runs (`INVESTIGATIONS.md` INV-3). We publish no model options. |
| Updating a function with `PATCH` | **`PUT`**; `PATCH` returns 405 with an empty body | `vogent/scripts/sync_functions.py` |
| Transition rules and the `field` key on question nodes | a question node's `equal` rule must carry **no field at all**. Naming `answer`, which is exactly what its own `outputSchema` calls the value, makes every rule fall through. Function nodes are the opposite: they require `field: "status"`. | proved by an isolated two-node probe: identical flow, only this differed. One routed, the other fell through. |

Verified by building, not by reading. The probe versioned prompts used to establish the node type
(`probe-freeform`, `probe-question`, `probe-function`) are left in the workspace; the API exposes no
delete for versioned prompts, and they are never dialled.

## 2b. Assumed, to be verified experimentally in Phase 4

| Assumption | How verified | If false |
|------------|--------------|----------|
| A1: `dial.inputs` in the function payload echoes `callAgentInput` | Inspect the first captured payload | Correlate by pre-registered `dial_id` only (already primary) |
| A2: an `equal` rule with `field: "status"` on a function node routes correctly, and a failed result falls through to the `always` rule | **Accepted by the API** (V2 stores 3 outcome-conditioned transitions). Still needs a real voice call to prove it routes at run time. | Freeform node whose prompt reads `{{node.transfer.status}}` and instructs the branch; test harder |
| A3: the endpoint may return a flat JSON object matching `outputs[]` | Same call | Wrap per whatever the captured error says |
| A4: function timeout ≥ 10 s, no automatic retry | Stub sleeps 8 s once; count POSTs | Tighten budgets; if retries exist, promote duplicate scenario to voice |
| A5: two concurrent browser dials are allowed | Two dials in the optimized run | Sequential; report no parallel savings |
| A6: `dial` in the payload may include a transcript snapshot | Inspect payload | Ordering comes from harness timestamps instead |

## 3. Manual workspace requirements (human)

Listed in `HUMAN_SETUP.md`: isolated workspace, secret API key, ability to create agents/functions/
versioned prompts, browser calls enabled, credit for roughly 25 short calls (≈ 25 × 90 s × $0.0015 ≈ $3.4).

## 4. Implementation decisions

- **Configuration as code.** `vogent/functions/*.json` (four function definitions) and
  `vogent/flows/v1.json`, `vogent/flows/v2.json` (flowDefinitions). `vogent/scripts/sync.py` creates or
  updates functions (patching `apiPath` to the current `BACKEND_PUBLIC_URL`), creates versioned prompts,
  and writes the resulting IDs to `vogent/ids.json` (git-ignored) and prints them. `vogent/scripts/export.py`
  pulls the live versioned prompts and functions back into `vogent/export/` so the submitted export is
  what actually ran.
- **Fallback if programmatic creation fails** (Gate in Phase 4): build the flows in the Flow Builder UI,
  export via `GET /agents/{id}/versioned_prompts` into `vogent/export/`, and document node-by-node in
  this file. Reproducibility is preserved by the export plus the function JSON.
- **Transfer is an `api` function**, not a `transfer` function: browser calls have no telephony to
  transfer, and the assignment requires a simulated transfer with inspectable state.
- **Versions are pinned per dial** with `versionedModelId`, so V1 and V2 runs are unambiguous and the
  efficiency experiment freezes one version.
- **`callAgentInput`** carries `scenario_id`, `evaluation_run_id`, `patient_ref` (synthetic).
- **`timeoutMinutes: 3`** caps runaway calls and cost.

## 5. Functions

All `type: api`, header `X-CareFlow-Token: <org token>` (set in the workspace, never in the repo),
`apiPath = BACKEND_PUBLIC_URL + /vogent/functions/<name>`.

| Function | Inputs (`inputJsonSchema`) | Outputs (node `outputs[]`) | Lifecycle message |
|----------|----------------------------|----------------------------|-------------------|
| `schedule_appointment` | `patient_ref`, `preferred_date`, `reason` | `status`, `appointment_id?`, `slot_iso?`, `agent_message` | V1: "Booking that for you now." · V2: "Let me check the schedule." |
| `transfer_triage` | `patient_ref`, `concern_summary`, `callback_phone` | `status`, `transfer_session_id?`, `failure_reason?`, `agent_message` | V1: "I'm connecting you to our triage nurse now." · V2: "Let me try to reach our triage nurse." |
| `create_callback` | `patient_ref`, `callback_phone`, `priority`, `reason_code` | `status`, `callback_id?`, `priority`, `agent_message` | "One moment." |
| `report_disposition` | `category`, `disposition`, `summary` | `status` | none (`awaitSpeech: true`) |

The V1 lifecycle message on `transfer_triage` is deliberately the realistic wording a builder would
choose. It is the promise. Whether it is truthful depends on the branch that follows.

## 6. Flow V1 — baseline (plausible, produces the reported failure)

`globalContext`: practice identity, the fictional policy, "never give medical advice", synthetic
patient reference handling.

| Node | Type | Content | Transitions (ordered) |
|------|------|---------|-----------------------|
| `greet_intake` | question (multiple_choice) | "Are you calling to schedule a routine appointment, or about a concern after a recent surgery?" options: `routine`, `post_op`, `other` | `Equal routine` → `collect_slot`; `Equal post_op` → `collect_concern`; `Always` → `other_help` |
| `collect_slot` | question (freeform) | preferred day and reason | `Always` → `book` |
| `book` | function_call `schedule_appointment` | inputs from `collect_slot` | `Always` → `close_scheduled` |
| `close_scheduled` | freeform | "You're all set for {{node.collect_slot.output}}. Anything else?" (reads the *request*, not the result) | `Always` → `disposition_resolved` |
| `collect_concern` | question (freeform) | brief description and best callback number | `Always` → `transfer` |
| `transfer` | function_call `transfer_triage` | inputs from `collect_concern` | `Always` → `close_transferred` |
| `close_transferred` | freeform | "They'll take it from here. Take care." | `Always` → `disposition_resolved` |
| `other_help` | freeform | explain limitation; if caller asks for a callback → `callback_on_request` else end | `Equal callback` → `callback_on_request`; `Always` → `disposition_unresolved` |
| `callback_on_request` | function_call `create_callback` (`normal`, `caller_requested`) | | `Always` → `disposition_resolved` |
| `disposition_resolved` | function_call `report_disposition` | `disposition: resolved` | end |
| `disposition_unresolved` | function_call `report_disposition` | `disposition: unresolved` | end |

Why it fails: `transfer → close_transferred` is unconditional; there is no failure-triggered callback;
the closing lines and the disposition repeat the promise. Scheduling reads back the request rather than
the booking result.

## 7. Flow V2 — evidence-aware

Same intake and collection nodes. Differences:

| Node | Type | Content | Transitions (ordered) |
|------|------|---------|-----------------------|
| `book` | function_call `schedule_appointment` | | `Equal booked` → `close_scheduled`; `Always` → `close_scheduling_failed` |
| `close_scheduled` | freeform | "Your appointment is booked: {{node.book.agent_message}}." | → `disposition_scheduled` |
| `close_scheduling_failed` | freeform | "I couldn't confirm a booking. Our office will follow up." | → `callback_scheduling` (create_callback normal, `unsupported_request`) → `disposition_unresolved` |
| `transfer` | function_call `transfer_triage` | | `Equal connected` → `close_transferred`; `Always` → `transfer_failed_notice` |
| `close_transferred` | freeform | "You're connected with our triage nurse now." | → `disposition_transferred` |
| `transfer_failed_notice` | freeform | "The transfer did not complete. I'm going to request an urgent callback from our nurse." | → `urgent_callback` |
| `urgent_callback` | function_call `create_callback` (`urgent`, `transfer_failed`, phone from `collect_concern`) | | `Equal created` → `close_callback_pending`; `Always` → `close_escalation_failed` |
| `close_callback_pending` | freeform | "A nurse will call you back at {{node.collect_concern.callback_phone}}. If your symptoms get worse, call the office line or emergency services." | → `disposition_callback_pending` |
| `close_escalation_failed` | freeform | "I could not complete the transfer or set up a callback. Please call the office directly at <synthetic number>; if this is an emergency call emergency services." | → `disposition_escalation_failed` |
| `other_help` | freeform | explain limitation, route to human via `create_callback(normal, unsupported_request)` | → `disposition_unresolved` |

Every closing line is downstream of the function result it describes. The disposition reported is the
one the evidence supports. Potential regressions to watch: longer calls (more turns → more cost);
`Equal` semantic matching mis-routing on unusual `status` strings; extra callback rows in scheduling
failure cases that staff may not want.

## 8. Identifiers and artifacts per run

Saved by the runner for every voice call: `dial_id`, `session_id`, `vogent_agent_id`,
`versioned_prompt_id`, `callAgentInput`, `startedAt/endedAt`, `aiDurationSeconds`, `systemResultType`,
transcript, harness timeline, function requests/responses (from the backend), evidence bundle, metrics.
Layout in `EVALUATION_PLAN.md §7`. The flow export that produced a run is referenced by
`versioned_prompt_id` in `vogent/export/`.

## 9. Billing and runtime evidence

`connected_seconds = aiDurationSeconds` from `GET /dials/{id}`. Dollars = seconds × `$0.0015` (standard
voice; `rate_source` recorded as the billing page URL and date) labelled **CALCULATED ESTIMATE**. After
each experiment, the Billing tab is checked; if per-call or per-day charges are visible, they are copied
into `artifacts/efficiency/billing.md` (screenshot with account details cropped) and labelled
**ACTUAL BILLED**. Other metered services: none planned (TTS via macOS `say`, local compute, ngrok free tier).
