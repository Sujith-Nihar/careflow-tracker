# Investigations Log

One entry per surprising result, written when it happens.

Template:

```
## INV-<n>: <one-line title>
Observed:        what happened (scenario_id, evaluation_run_id, dial_id, call_id, action_execution_ids)
Evidence:        the rows / payloads / transcript lines that show it (paths under artifacts/)
Assumption:      what we believed beforehand
Was it wrong:    yes / no / partly, and why
Change made:     code, flow, scenario, or metric changed
Re-evaluation:   new dial_id(s) and outcome
```

---

## INV-1: The first real voice call was 150 seconds of billed silence

**Observed.** The first voice run of `A_routine_scheduling` against V2 failed with
`derived_status = no_action_recorded` and no action executions at all.

| | |
|---|---|
| evaluation_run_id | `e553876f-77ba-490b-bedd-abb1a2ac6492` |
| dial_id | `ca41bf8a-adb1-4a9f-852e-7fbedf69b1be` |
| versioned_prompt_id | `32033ebe-188f-4116-a756-260b17481a0e` (V2) |
| systemResultType | `USER_HANGUP` |
| aiDurationSeconds | 150 |
| cost | $0.2250 (CALCULATED_ESTIMATE) |
| failed metrics | `intent_correct`, `required_executions_present`, `derived_status_expected`, `staff_action_expected` |

**Evidence.** `artifacts/v2/e553876f-77ba-490b-bedd-abb1a2ac6492/A_routine_scheduling/`.
The harness timeline holds three events and stops: `ready`, `audio_connected`, `status: in-progress`.
The page transcript is empty. Vogent's own dial record also has zero transcript segments. The backend
received `dial.created`, `dial.transcript` and `dial.updated` webhooks but no function call. So the
media session was established and the call ran for its full duration with nobody speaking at all.

**Assumption.** That the agent speaks first on a browser call, because the flow's entry node is a
`question` node with an opening line and `openingLineType` is `INBOUND_OUTBOUND`. The harness was built
around it: wait for the agent's text to settle, then reply.

**Was it wrong.** Yes, and the failure mode was worse than a wrong answer. The agent waited for the
caller, the caller waited for the agent, and neither side had a timeout that fired before the meter did.
A deadlock in a scripted conversation is invisible in a transcript test because there is no transcript.

**Change made.** Three changes in `evals/runner/harness.py`:
1. The caller now opens the conversation after 6 seconds of silence instead of waiting indefinitely. A
   real caller who hears nothing starts talking.
2. A call where the agent has still said nothing after 35 seconds is abandoned and marked `ERROR`,
   rather than paying to the ceiling. A longer wait would not have diagnosed it any better.
3. The per-call ceiling dropped from 150 to 100 seconds.

The abandonment is recorded as `ERROR`, distinct from `FAIL`. A harness problem must never be counted
as evidence about the agent.

**Also confirmed by this run** (assumption A1 in `VOGENT_PLAN.md`): `dial.inputs` echoes
`callAgentInput` exactly, including `scenario_id` and `evaluation_run_id`. That is what lets the backend
prefer dial-level identifiers over values the model repeats back.

**Re-evaluation.** Pending: re-run of `A_routine_scheduling` on V2 after the harness change.

---

## INV-2: The agent never spoke, because a question node cannot open a call

**Observed.** After fixing the harness deadlock (INV-1), the caller opened the conversation and Vogent
transcribed it correctly, but the agent still said nothing and the call was abandoned at 35 seconds.

| | |
|---|---|
| evaluation_run_id | `297281b0-386e-4691-8c11-5b57d9b12af3` |
| dial_id | `2e4b6a06...` |
| aiDurationSeconds | 35 |
| cost | $0.0525 (CALCULATED_ESTIMATE) |

**Evidence.** `artifacts/v2/297281b0-386e-4691-8c11-5b57d9b12af3/A_routine_scheduling/`.
Vogent's dial record holds exactly one transcript segment, and it is the caller:
`HUMAN: "Hi. I'd like to book a routine for an up appointment, please."` (6.45s to 9.89s). So the
synthetic audio reached Vogent and its speech recognition worked. The mishearing of "follow-up" as
"for an up" is ordinary recognition behaviour and did not affect routing. No AI segment ever appeared.

**Assumption.** That the flow's entry node, a `question` node with an opening line and
`openingLineType: INBOUND_OUTBOUND`, would make the agent greet the caller.

**Was it wrong.** Yes. Two separate things were wrong, and the first one hid the second.

1. The stored flow has `aiOpen: false`. Publishing `aiOpen: true` does not change it; the field is
   accepted and ignored, which matches the documentation calling it deprecated. It is therefore not
   the lever, despite being the field that describes the behaviour.
2. A **question node cannot open a call.** Proved by isolation: a one-node flow whose only node is a
   `freeform` (versioned prompt `d11d964b-e191-43e7-84cb-acf909783c9e`) greeted the caller within one
   second of audio connecting. The same workspace, the same model, the same `openingLineType`. The only
   difference was the entry node's type.

**Change made.** Both flows now begin with a `freeform` greeting node that transitions to the existing
question node. The change is identical in V1 and V2, so the comparison between them is unaffected.

**Re-evaluation: the fix did not work, and the diagnosis was wrong.** Run
`301531c5-6a3a-4e97-9b66-10af3e40203c` on V2 `251e150f-1b68-46f2-8d5e-7754c864dbcf` was silent again.
The dial record confirms the new version ran and the caller was heard. A three-way bisect then showed a
one-node freeform flow, a freeform plus question flow, and a freeform plus question plus function flow
all greeted the caller within one second, using the same long policy context. So the entry node type
was never the cause. The real cause is INV-3. The greeting node is kept because it is better
conversational design, but it fixed nothing.

**Also found while diagnosing this.** A question node exposes its answer as `answer`, not `output`, so
every `{{node.<id>.output}}` template in both flows referenced a field that does not exist. Function
nodes do expose `status` as expected, which is what the V2 outcome-conditioned transitions branch on.

**What this says about the eval design.** Both INV-1 and INV-2 are failures that a transcript test or a
structural check would have scored as a pass or not seen at all: in one case there was no transcript,
in the other the flow graph was perfectly well-formed. Only placing a real call surfaced them.

---

## INV-3: A temperature setting made the agent mute

**Observed.** Four consecutive voice runs produced an agent that never spoke, while isolated probe
flows on the same agent, model and workspace spoke within one second every time.

**Evidence.** A bisect that held the flow definition completely fixed at the real 22-node V2 graph and
varied only what was published alongside it:

| Published alongside the identical flow | Result |
|----------------------------------------|--------|
| nothing | spoke at 1s |
| `modelOptionValues: [temperature 0.2]` | **silent** |
| `modelOptionValues: [temperature 0.2, max_tokens 600]` | **silent** |
| `modelOptionValues: [temperature 1.0]` (the model's own default) | spoke at 1s |

**Assumption.** That a low temperature was a free win: this is a clinical routing flow, so less
variance between runs is better, and the option is offered by the model's own metadata
(`{"id": "temperature", "valueType": "FLOAT", "default": "1.0"}`).

**Was it wrong.** Yes, and silently. `POST /agents/{id}/versioned_prompts` accepts the value and
returns 200. The flow stores and exports cleanly. Every structural check passes. The agent then simply
never produces an utterance, on every call, with no error surfaced anywhere: not in the dial record,
not in `aiResult`, not in a webhook. The only symptom is silence, which costs money to observe.

**Change made.** `vogent/scripts/sync_flows.py` no longer publishes `modelOptionValues`. Both versions
run the model's default settings.

**What it costs us.** Run-to-run variance is higher than I wanted. Since V1 and V2 now use identical
model settings, the comparison between them is still sound, but a single call is weaker evidence than
it would have been at a low temperature. This is recorded as a limitation of the suite rather than
papered over.

**Re-evaluation.** Republished as V1 `048c8db3-852c-4527-ba30-e94843ee46b0` and
V2 `9cf208b3-14f6-4d34-9735-361877a2f566`.

**Why this matters beyond Vogent.** It is the project's own thesis turned on the tooling: a
configuration that is accepted, stored, and passes every structural check is not evidence that it
works. Only running it and observing the result is. Four runs and about $0.18 were spent on a setting
that looked correct in every artifact.

---

## INV-4: Function nodes cannot branch on their own result, so the decision moved to the backend

**Observed.** Run `f25ab060-3103-4a0f-b8ef-23364f7abe30` PASSED scenario A on V2 with a complete and
correct evidence chain: the scheduler was called with "Next Tuesday", booked an appointment, and the
derived status was `completed_scheduled` with no staff action needed.

But the transcript shows the agent telling the caller **"I could not confirm the booking today"** while
the function had returned `status: booked` and an appointment row existed. The metrics scored it a pass
because the metrics read state, and the state was right. The caller was told the opposite of the truth.

**Evidence.** Two isolated probes, identical flows, varying only the transition rule on a function node
whose backend demonstrably returned `status: "connected"` (confirmed in the backend log):

| Transition rule on the function node | Branch taken |
|---------------------------------------|--------------|
| `equal`, `field: "status"`, value `connected` | fell through to `always` |
| `equal`, no field, value `connected` | fell through to `always` |
| `in`, `field: "status"`, values `[connected]` | fell through to `always` |
| downstream freeform reading `{{node.fn.status}}` | spoke **"BRANCH VALUE IS connected"** |

So the result is fully available to later prompts, and transition conditions on function nodes simply
never evaluate against it. This is assumption A2 in `VOGENT_PLAN.md`, and it is false.

**Was the assumption wrong.** Yes, and it was the mechanism V2's entire design rested on.

**Change made.** Two changes, both of which arguably improve the design rather than merely work around it.

1. **Speech reads the real value.** After every function call the flow goes to a freeform node whose
   prompt contains the literal result, `{{node.transfer.status}}`, with an instruction that names the
   exact value required before the agent may claim success. The agent cannot claim a transfer without
   the word `connected` being in front of it.
2. **The escalation decision moved into the backend.** The flow now always asks for a callback after a
   transfer attempt, and `create_callback` consults the persisted transfer sessions for that call. If a
   transfer actually connected it returns `not_needed` and creates nothing, recorded as a new action
   outcome `not_applicable`: asked for, correctly declined. Not a success, not a failure.

That second change puts the decision where the authoritative state already lives, instead of asking a
language model to re-derive it from a string. The flow no longer needs to be trusted with it.

**What it costs.** V2's post-operative path is now linear, so the graph itself no longer encodes the
policy branch, and the structural preflight check in the efficiency experiment must be rewritten: the
old rule counted outcome-conditioned edges, and the correct rule is now that every closing line must
sit downstream of the function whose result it describes and must reference that result.

**A note on the metric gap this exposed.** Scenario A passed while the agent said something false,
because no metric compared the agent's claim about the booking against the booking. The deterministic
state metrics are sound; the truthfulness coverage was thinner than intended on the scheduling path,
where only the post-operative scenarios had a required `must_disclose`. That is a real weakness in my
own suite, found by reading a transcript on a passing run.

---

## INV-5: A function input value is a template, not a prompt

**Observed.** With `report_disposition` finally recording (it had been returning 500 on every
call, see below), the definitive V2 run scored 0 of 4 on `disposition_truthful` while every
derived status was correct.

| Scenario | Derived status | Agent filed | Summary it filed alongside |
|----------|----------------|-------------|-----------------------------|
| A | `completed_scheduled` | `unresolved` | "Scheduler returned booked." |
| B | `completed_transferred` | `escalation_failed` | "Transfer connected, callback not_needed." |
| C | `callback_pending` | `escalation_failed` | "Transfer failed, callback created." |
| D | `escalation_failed` | `escalation_failed` | "Transfer failed, callback failed." |

**Evidence.** The `summary` field is free text and resolved perfectly every time: "Transfer
connected, callback not_needed" is exactly right. So `{{node.<id>.status}}` substitution works.
The `disposition` field carried a rule — *"transferred when {{node.transfer.status}} is
connected, otherwise callback_pending when ... is created, otherwise escalation_failed"* — and
the model never evaluated it. Vogent substituted the values and passed the sentence through as
literal text.

**Assumption.** That a function input value is a place the model reasons, the way a node prompt
is. It is not: it is a template. Substitution happens; evaluation does not.

**Was it wrong.** Yes, and my parser made it worse. It scanned the resulting sentence for any
term it recognised, longest first, so "…otherwise escalation_failed" always won and A's sentence
matched `unresolved` ahead of `scheduled`. A flow bug was being converted into a plausible wrong
answer instead of an obvious one. The parser is now strict: an exact term or a known alias, and
nothing else.

**Change made.** V2 no longer files a disposition at all. Its graph is linear, because function
nodes cannot branch on their own result (INV-4), so it has no way to choose the right one — and
a confidently wrong disposition is worse than none, since the disposition is precisely the
"agent's claim" half of the comparison this project is built on.

V2's claim is now what it actually told the caller, read from the recording. That is the more
meaningful claim anyway: it is what the patient heard. V1 keeps its disposition node, because
V1's value is the fixed literal `resolved` and needs no evaluation — filing "resolved" whatever
happened *is* the reported bug.

`disposition_truthful` now reports **not applicable** when no disposition was filed, rather than
passing. A metric that passes because its input is missing looks like coverage and is not.

**Found on the way.** `report_disposition` was the one function route with no error handling, so
a validation failure became an HTTP 500 rather than a 200 with `invalid_input`. Every other
function already did the right thing. The agent's account of four consecutive suites was being
discarded, and because the metric passed vacuously without it, nothing flagged it. The dashboard
showing "Not recorded" in the intent column is what surfaced it.
