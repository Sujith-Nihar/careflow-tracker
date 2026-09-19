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

**Re-evaluation.** Republished as V1 `5f2c2d40-c2ae-47e3-8681-1e951c92c9c2` and
V2 `251e150f-1b68-46f2-8d5e-7754c864dbcf`; re-run pending.

**Also found while diagnosing this.** A question node exposes its answer as `answer`, not `output`, so
every `{{node.<id>.output}}` template in both flows referenced a field that does not exist. Function
nodes do expose `status` as expected, which is what the V2 outcome-conditioned transitions branch on.

**What this says about the eval design.** Both INV-1 and INV-2 are failures that a transcript test or a
structural check would have scored as a pass or not seen at all: in one case there was no transcript,
in the other the flow graph was perfectly well-formed. Only placing a real call surfaced them.
