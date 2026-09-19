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
