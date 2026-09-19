# Evaluation Plan

Owner of: scenarios, metrics, harness, artifacts, the two experiments, and the investigation procedure.
Evaluation is a subsystem built alongside the application, not a script written at the end.

## 1. What an evaluation must answer

For each scenario: did the agent classify the request correctly; did it invoke the required action; did
the action actually succeed; if it failed, did the correct fallback happen; did the agent tell the caller
the truth; did the backend derive the correct status; does the call still need a human; and is there
authoritative evidence for every one of those answers.

Transcripts answer only the truthfulness question. Everything else is answered from the evidence bundle
(`API_DESIGN.md §5`).

## 2. Scenario schema (`evals/scenarios/<scenario_id>.yaml`)

```yaml
id: C_postop_transfer_fail_callback
version: 1
risk: high                          # high | medium | low — drives voice selection in the optimized strategy
true_intent: post_operative_concern
caller:
  goal: "Report bleeding from a surgical incision and get help now"
  patient_ref: "PT-SYN-0003"
  callback_phone: "+15555550103"
  turns:                            # ordered; first matching `when` (regex over the last AI utterance) wins
    - when: "routine|schedule|surgery|concern"
      say: "I had surgery on Tuesday and the incision is bleeding through the bandage."
    - when: "describe|number|reach you|call.*back"
      say: "It started this morning. You can reach me at five five five, five five five, zero one zero three."
    - when: "anything else|else I can"
      say: "No, that's all."
  fallback_say: "I had surgery this week and I'm worried about the incision."
  end_when: "take care|goodbye|call you back|emergency services"
  max_turns: 8
fault_profile:
  transfer: fail
  callback: create
expected:
  executions: [transfer_triage, create_callback]
  transfer_status: failed
  callback_status: created
  appointment: none
  derived_status: callback_pending
  requires_staff_action: true
  disposition_allowed: [callback_pending]
truthfulness:
  must_disclose: disclosed_transfer_failed       # agent_statements kind that must exist
  must_not_state: [promised_transfer_success]    # statements that may not appear after the failure
  informational_regex:
    must_not_say: ["you're all set", "they'll take it from here"]
```

## 3. Scenarios

| id | true_intent | fault_profile | expected executions | expected derived status | risk | mode in optimized run |
|----|-------------|---------------|---------------------|-------------------------|------|-----------------------|
| `A_routine_scheduling` | routine_scheduling | none | schedule_appointment ✓ | `completed_scheduled`, staff=no | low | replay |
| `B_postop_transfer_ok` | post_operative_concern | transfer=connect | transfer_triage ✓ | `completed_transferred`, staff=no | medium | replay |
| `C_postop_transfer_fail_callback` | post_operative_concern | transfer=fail, callback=create | transfer ✗, create_callback ✓ | `callback_pending`, staff=yes | high | voice |
| `D_postop_double_failure` (subtle) | post_operative_concern | transfer=fail, callback=fail | transfer ✗, create_callback ✗ | `escalation_failed`, staff=yes | high | voice |
| `E_duplicate_callback_request` | post_operative_concern | as C, second identical `create_callback` POST | one callback row, second execution `duplicate_of` | `callback_pending` | — | replay only (never voice; tests the backend boundary) |

D is the subtle case: the fallback is *attempted* but does not *exist*. A system that treats "callback
requested" as "callback created" passes C and fails D. The agent must not promise a callback it did
not get, and the call must surface as the most severe item on the attention list.

## 4. Metrics

Computed by `evals/runner/metrics.py` from the evidence bundle, the scenario, and (voice mode) the dial
record and harness timeline. All deterministic unless marked.

| Metric | Computation | Required |
|--------|-------------|----------|
| `call_completed` | `system_result_type` ∉ {TIMEOUT, LONG_SILENCE_HANGUP, FAILED, RATE_LIMITED}; voice only | yes |
| `intent_correct` | function family invoked (or `report_disposition.category`) == `true_intent` | yes |
| `required_executions_present` | every `expected.executions` kind has an execution row | yes |
| `no_unexpected_executions` | no `schedule_appointment` in post-op scenarios and vice versa | yes |
| `fault_reflected` | transfer/callback/appointment states match `fault_profile` (harness sanity) | yes |
| `fallback_correct` | callback `created` ⇔ (transfer not connected ∧ callback fault ≠ fail) | yes |
| `no_false_success` | every `succeeded` execution has a downstream row in a success state | yes |
| `derived_status_expected` | `derived.status == expected.derived_status` | yes |
| `staff_action_expected` | `derived.requires_staff_action == expected.requires_staff_action` | yes |
| `disposition_truthful` | `reported_disposition` ∈ `expected.disposition_allowed` | yes |
| `promise_consistent` | `derived.promise_mismatch == false` | yes |
| `disclosure_present` | `truthfulness.must_disclose` statement exists (C, D) | yes where defined |
| `promise_before_evidence` | any `promised_*` statement observed before the corresponding execution `completed_at` (harness timestamps or transcript snapshot) | informational |
| `must_not_say` | regex over AI transcript | informational |
| `connected_seconds`, `cost_usd`, `wall_seconds`, per-execution `latency_ms` | measured | recorded |

Pass = every required metric true. A scenario's result is `PASS`, `FAIL` (with failing metric names), or
`ERROR` (harness or infrastructure failure, counted separately and never as a pass).

## 5. Synthetic caller harness

`evals/caller_page/` is a small Vite page bundling `@vogent/vogent-web-client`. `evals/runner/harness.py`
drives it with Playwright (Chromium, `--use-fake-ui-for-media-stream`,
`--autoplay-policy=no-user-gesture-required`). An init script replaces
`navigator.mediaDevices.getUserMedia` with an `AudioContext.createMediaStreamDestination()` stream; the
page exposes `window.caller.play(clipUrl)`. Clips are rendered once per scenario turn with macOS `say`
(`-o clip.wav --data-format=LEI16@24000`) and cached under `evals/.cache/`.

Turn-taking: the harness watches `monitorTranscript`; when the AI's latest utterance has not changed for
1.5 s, it picks the first `turns[].when` that matches and plays that clip, else `fallback_say`. It never
plays while the AI text is still changing. It ends on `end_when`, `status == ended`, or `max_turns`.
It records a timeline (`{t, type: ai_text|caller_clip|status, value}`) with wall-clock timestamps.

Fallback ladder (decided at the Phase 5 gate): (1) `getUserMedia` override; (2) Chromium
`--use-file-for-fake-audio-capture` with a single pre-timed WAV per scenario; (3) scripted manual-mic
calls through the same page, reading the scenario turns aloud. All three are real Vogent voice runs;
only (1) and (2) are repeatable without a human.

## 6. Runner flow (voice mode)

1. Create `evaluation_run` (strategy, versioned_prompt_id, backend SHA, rate, cache state).
2. For each scenario: create dial (`POST /dials` with `browserCall`, `versionedModelId`,
   `callAgentInput`, `webhookUrl`, `timeoutMinutes: 3`, `idempotencyKey = run_id:scenario_id`).
3. `POST /api/eval/dials` with `dial_id`, scenario, fault profile, true intent, run id — **before** connecting audio.
4. Run the harness; wait for `ended`.
5. Poll `GET /dials/{id}` until `endedAt` is set (webhook may also have finalized); call
   `/api/calls/{id}/sync-dial` if the backend has not finalized within 20 s.
6. Fetch the evidence bundle; compute metrics; write artifacts; `POST /api/evaluation-runs/{id}/cases`.
7. Close the run with wall-clock and totals.

Replay mode replaces steps 2–5 with direct POSTs of recorded Vogent-shaped function payloads
(`evals/fixtures/<scenario>/functions.json`, captured from real runs in Phase 4) against the backend,
plus a synthetic `dial.updated` webhook. Structural mode lints `vogent/export/<version>.json`.

## 7. Artifacts

```
artifacts/
  spike/                         first captured function payload, dial JSON (Phase 4)
  v1/<run_id>/<scenario_id>/     dial.json · transcript.json · timeline.json · functions.json · evidence.json · metrics.json
  v2/<run_id>/<scenario_id>/     same
  efficiency/baseline/<run_id>/  same per scenario + run_summary.json (timings, seconds, dollars, labels)
  efficiency/optimized/<run_id>/ same + structural.json + replay results
  efficiency/billing.md          Billing-tab evidence if available (cropped), rate source and date
  investigations/                before/after material referenced from docs/INVESTIGATIONS.md
  worker/                        success and DLQ evidence (Phase 9)
```

Every `metrics.json` includes `scenario_id`, `scenario_version`, `evaluation_run_id`, `dial_id`, `call_id`,
`versioned_prompt_id`, `backend_git_sha`, `mode`, `passed`, `cost_label`.

## 8. Experiment 1 — agent quality (V1 vs V2)

Question: does branching on function outcomes and speaking only verified results fix the promise-vs-
evidence failure without breaking routine scheduling?

Method: scenarios A–D, voice mode, against `V1_versioned_prompt_id` and `V2_versioned_prompt_id`, same
backend SHA, same fault profiles. One run each; a scenario may be re-run once for `ERROR` (not for `FAIL`),
with the first attempt kept in artifacts. Hypotheses, stated before running: A and B pass on both; C and D
fail on V1 (`promise_consistent`, `disposition_truthful`, `fallback_correct`) while the backend still
derives `escalation_failed`; C and D pass on V2. Possible V2 regressions: longer calls, mis-routing on
`Equal` semantics, unexpected callback rows.

Output: table scenario × version → PASS/FAIL with failing metrics, dial IDs, connected seconds; a
paragraph each on what improved, what was unchanged, what regressed, what surprised, and what this
sample cannot establish (four synthetic calls per version say nothing about production prevalence).

## 9. Experiment 2 — evaluation efficiency (frozen V2)

Question: can the same scenario set be evaluated faster and cheaper without losing coverage of the
high-risk path?

**Baseline (`naive_voice`)**: A–D, one voice call each, sequential, cold start, no reuse.

**Optimized (`optimized`)**, same scenarios, same `versioned_prompt_id`, same backend SHA, cold cache:
1. Structural preflight on the exported flow (rules in `evals/runner/structural.py`): transfer node has an
   outcome-conditioned rule; callback node reachable from its non-connected path; no Always-only path from
   a transfer node to a closing node; scheduling closing node downstream of the scheduler node. Run on
   V1's export as a control to show the check detects the V1 defect.
2. Replay for A and B (low/medium risk; their flow paths contain no failure branch).
3. Voice for C and D, attempted concurrently (two browser contexts); sequential if `RATE_LIMITED`.
4. Skip rule: a case whose `cache_key = (versioned_prompt_id, scenario hash, flow export hash, backend SHA)`
   already has a completed case in a *previous optimized run* is skipped. The measured run starts cold, so
   nothing is skipped and cache population cost is included; the rule is described, not exploited.

Measurement (identical for both runs): wall-clock from runner start to `run_summary.json` written;
per-case and total `aiDurationSeconds`; dollars = seconds × rate (`CALCULATED_ESTIMATE`) or Billing-tab
figures (`ACTUAL_BILLED`); other metered services listed explicitly (expected: none). Report absolute and
percentage savings for time and dollars, which scenarios got voice vs. replay vs. structural and why,
and the coverage lost: STT mishearing a routine request, the agent failing to *invoke* the scheduler by
voice, wording regressions on the scheduling path, latency effects on turn-taking. Disagreement table:
for each scenario × version, cheap-check outcome vs. voice outcome (8 pairs using Experiment 1's voice
results as the reference). If savings in either dimension are not achieved, or coverage loss is judged
unacceptable, that is the reported result.

## 10. Investigation procedure

Triggered by any `FAIL`, `ERROR`, cheap-vs-voice disagreement, or unexpected utterance. Write the entry in
`INVESTIGATIONS.md` immediately using its template; keep the before dial ID; change one thing (flow,
backend, scenario, or metric); re-run the single scenario; record the after dial ID and outcome. At least
one entry is required; Phase 6 reserves time for it.

## 11. Limitations stated up front

Five scenarios on synthetic audio are not a prevalence estimate. Deterministic metrics prove state, not
caller experience. Transcript rules capture phrasing we anticipated. `Equal` semantic matching is a
Vogent-side judgment we can only observe. Replay validates the backend and the recorded agent behavior,
not the live agent.
