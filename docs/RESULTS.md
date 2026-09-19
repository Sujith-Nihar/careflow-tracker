# Results

Two separate experiments. Agent quality (V1 vs V2) is not mixed with evaluation
efficiency (naive vs optimised). Every dollar figure is a **CALCULATED ESTIMATE** from
`aiDurationSeconds × $0.0015`, the standard-voice rate published at
docs.vogent.ai/platform-overview/billing (read 2026-09-18). No figure here is a billed charge.

---

## Experiment 1 — Agent quality: V1 vs V2

Same agent, same four functions, same model and settings, same scenarios, same synthetic
caller audio. Only the flow differs.

| Run | Version | Versioned prompt | Artifacts |
|-----|---------|------------------|-----------|
| `36c35af7-9fef-4323-86cb-94612c002a1e` | V1 baseline | `139c8c53-d3c9-42c9-92f8-07611abdcb30` | `artifacts/v1/` |
| `4d5286d0-f0c2-4906-8be0-57c140881af4` | V2 evidence-aware | `0d16bb48-afe1-4b0c-9a7b-c155f5098fb0` | `artifacts/efficiency/baseline/` |

### Per-scenario outcome

| Scenario | V1 | V2 | V1 derived status | V2 derived status |
|----------|----|----|-------------------|-------------------|
| A routine scheduling | PASS | PASS | `completed_scheduled` | `completed_scheduled` |
| B post-op, transfer connects | FAIL | PASS | `no_action_recorded` | `completed_transferred` |
| C post-op, transfer fails | FAIL | PASS | `no_action_recorded` | `callback_pending` |
| D post-op, both fail | FAIL | FAIL¹ | `no_action_recorded` | `escalation_failed` |
| **Totals** | **1/4** | **3/4** | 365s wall, 213s connected, $0.3195 | 285s wall, 148s connected, $0.2220 |

¹ D's state evidence was correct on every run; only the transcript-derived
`disclosure_present` metric failed, and it passed on an isolated re-run
(`310d2b9f-5855-4344-b0d8-907a3df06ea9`, dial `885c128d`). See "What this cannot establish".

### What V1 actually did — the reported failure, reproduced

V1, scenario C, dial `8633e361`:

```
AI   : What's the best number to reach you on?
HUMAN: It started this morning. You can reach me at 5 5 5 5 5 5 0 1 0 3.
AI   : I'm connecting you to the triage nurse now.
```

Action executions recorded: **none**. Agent statements: `promised_transfer` ×2.
Derived status: `no_action_recorded`, `promise_mismatch = true`.

A caller reporting a bleeding surgical wound was told they were being connected to a nurse.
Nothing was attempted. This is the practice manager's complaint, reproduced on a real call.

The backend caught it regardless of what the flow did: absence of evidence produced
`no_action_recorded` and flagged the promise as unmatched, rather than accepting the agent's
account of the call.

### What V2 changed

V2 never speaks about an outcome before it has one. Every closing line sits downstream of the
function whose result it describes and reads that result literally. On C, dial `01ff9f29`:
the transfer failed, an urgent callback was created, and the agent said "The transfer did not
complete" instead of claiming a transfer.

More importantly, V2's escalation does not depend on the model at all. The flow always requests a
callback after a transfer attempt, and the backend decides whether one is warranted from the
persisted transfer result. Even if the wording drifted, the callback would still exist.

### A confound I am not going to paper over

V1's post-operative failures are **over-determined**. Two things are true at once:

1. **The design flaw being tested.** V1 announces the transfer before attempting it and closes
   unconditionally afterwards, reporting `resolved` regardless of outcome.
2. **A platform limitation I found while building.** V1's announcement is a `freeform` node placed
   before the function node, and freeform nodes do not reliably advance on an `always` transition
   (`INVESTIGATIONS.md`). So V1 often never reaches its own transfer function at all.

So the honest reading is not "V1 calls the transfer and mis-reports the result". It is "V1's
naive structure — announce, then act — fails in two compounding ways on this platform: it may
never act, and if it does it will not check". The second alone would justify V2; the first makes
the failure worse and is itself a finding about naive flow authoring here.

To isolate flaw 1 cleanly, V1's promise would need to move into the function's lifecycle message
so the function is definitely invoked. That is the first thing I would run with more budget.

### What improved, what did not, what surprised

- **Improved.** Post-operative handling end to end: 0/3 to 2/3 on state metrics, with the third
  correct on state and flaky only on transcript wording. `promise_consistent` went from failing on
  every post-operative call to passing on all of them.
- **Unchanged.** Routine scheduling passes on both. V2's rework did not regress it.
- **Regressed.** Nothing measured. V2 calls one more function per post-operative call
  (`create_callback` even when not needed), which the backend answers `not_applicable`. That is
  one extra round trip per call for a guarantee that does not depend on the model.
- **Surprised me.** V1 was worse than designed. I expected it to attempt transfers and misreport
  them; it frequently never attempted them.

### What this cannot establish

Four scenarios, one run each per version, on synthetic audio, is not a prevalence estimate and
says nothing about production rates. The model runs at its default temperature because any lower
setting makes the agent mute (`INVESTIGATIONS.md` INV-3), so run-to-run variance is higher than I
wanted: scenario D passed in isolation and failed in the suite with identical state evidence.
Deterministic state metrics were stable across every run; transcript-derived metrics were not.
That ordering is the reason the architecture treats system state as authoritative.

---

## Experiment 2 — Evaluation efficiency

### Naive baseline (frozen V2 `0d16bb48-afe1-4b0c-9a7b-c155f5098fb0`)

Every scenario gets a full browser voice call, sequential, no filtering, no reuse.
Run `4d5286d0-f0c2-4906-8be0-57c140881af4`.

| Scenario | Mode | Connected | Cost | Result |
|----------|------|-----------|------|--------|
| A | voice | 51s | $0.0765 | PASS |
| B | voice | 37s | $0.0555 | PASS |
| C | voice | 30s | $0.0450 | PASS |
| D | voice | 30s | $0.0450 | FAIL (transcript metric) |
| **Total** | | **148s** | **$0.2220** | 285s wall-clock |

### Optimised run

Same four scenarios, same frozen version, same metrics, same measurement code.
Run `d7fc7213-97b1-45be-8602-2063a9c0041f`. Cold cache; nothing reused from the naive run.

| Scenario | Mode | Why this mode | Connected | Cost | Result |
|----------|------|---------------|-----------|------|--------|
| structural preflight | lint | gates the rest; fails fast on a flow that cannot speak the truth | 0.0002s | $0 | PASS |
| A | replay | no failure branch on this path; backend behaviour fully exercised without voice | 0s | $0 | PASS |
| B | replay | same | 0s | $0 | PASS |
| C | **voice** | high-risk transfer and callback path | 33s | $0.0495 | PASS |
| D | **voice** | high-risk, and the subtle double failure | 29s | $0.0435 | PASS |
| **Total** | | | **62s** | **$0.0930** | 4/4, 198s wall-clock |

### Measured savings

| Measure | Naive | Optimised | Absolute | Percent |
|---------|-------|-----------|----------|---------|
| Wall-clock | 285s | 198s | −87s | **−30.5%** |
| Connected seconds | 148s | 62s | −86s | **−58.1%** |
| Dollars (estimate) | $0.2220 | $0.0930 | −$0.1290 | **−58.1%** |
| Voice calls | 4 | 2 | −2 | −50% |

Both dimensions improved. Wall-clock falls by less than dollars because the fixed
overhead of the run — browser startup, dial creation, polling for the finalised dial
record — is unchanged for the two scenarios that still make calls, and replay still
costs real seconds against a hosted database.

Other metered services: none. The synthetic caller's speech is rendered locally by the
macOS speech synthesiser at no cost, the tunnel is on a free tier, and the database and
compute are local or already paid for. So every dollar in this comparison is Vogent's.

### Coverage given up

The optimised run buys its savings by not making two calls. What those calls would have
covered, and now do not:

- **Speech recognition on the routine path.** A and B no longer exercise recognition at
  all. This is a real loss: recognition destroyed the caller's words for several runs
  during development, and only a voice call exposed it. A regression in the intake
  wording would pass the optimised suite.
- **Whether the agent invokes the scheduler at all by voice.** Replay posts the function
  call itself, so it proves the backend and the recorded agent behaviour, not the live
  agent's decision to act.
- **Turn-taking and latency on the routine path.** Timing effects that only appear in a
  real conversation.
- **Wording regressions on the scheduling confirmation.** The structural check verifies
  that the node reads `{{node.book.status}}`, but not what the agent actually says.

What the optimised run still covers in full: both high-risk paths end to end on real
voice, the complete evidence chain for every scenario, and every deterministic state
metric. The check that a flow is capable of truthful speech runs on every version.

### Disagreement between cheap checks and voice runs

For the two scenarios that changed mode, comparing the same scenario across the two runs:

| Scenario | Naive (voice) | Optimised (replay) | Agree? |
|----------|---------------|--------------------|--------|
| A | PASS `completed_scheduled` | PASS `completed_scheduled` | yes |
| B | PASS `completed_transferred` | PASS `completed_transferred` | yes |

No disagreement on this sample, which is a weak result rather than a reassuring one: two
scenarios, one run each, both already passing. It shows the replay path does not
contradict voice; it does not show it would catch a voice-only regression. It would not.

One difference is worth stating and is **not** a cheap-check disagreement: scenario D
failed the naive run and passed the optimised run, both on real voice, with identical
state evidence. The failing metric was `disclosure_present`, which reads the transcript.
That is model variance at the default temperature (`INVESTIGATIONS.md` INV-3), and it is
the strongest argument in these results for weighting state evidence over speech.

### Honest reading

The saving is real and measured, but it is modest in absolute terms: about $0.13 and 87
seconds on a four-scenario suite. The strategy matters more at scale, where the replay
and structural paths stay near-free as scenarios are added while voice cost grows
linearly. On a suite this small, the fixed overhead dominates.

