# Results

Two separate experiments. Agent quality (V1 vs V2) is not mixed with evaluation
efficiency (naive vs optimised). Every dollar figure is a **CALCULATED ESTIMATE** from
`aiDurationSeconds × $0.0015`, the standard-voice rate published at
docs.vogent.ai/platform-overview/billing (read 2026-09-18). No figure here is a billed
charge. No other metered service was used: speech synthesis is local, the tunnel is free
tier, compute and database are already paid for.

The database was cleared before these runs, so every call referenced below is reproducible
from the artifacts and visible in the dashboard.

---

## Experiment 1 — Agent quality: V1 vs V2

Same agent, same four functions, same model and settings, same scenarios, same synthetic
caller audio, same harness code. Only the flow differs.

| Run | Version | Versioned prompt | Artifacts |
|-----|---------|------------------|-----------|
| `278133e5-85c5-4bd0-91da-b2952cf11519` | V1 baseline | `d37760bc-a8a3-4e7f-80d1-247264cd4a94` | `artifacts/v1/` |
| `febdde6d-33a7-40e1-a18b-f530bbe6e65a` | V2 evidence-aware | `dfc9502a-073c-42f0-b8f2-77afe4a35123` | `artifacts/efficiency/baseline/` |

### Per-scenario outcome

| Scenario | V1 | V2 | V1 derived status | V2 derived status |
|----------|----|----|-------------------|-------------------|
| A routine scheduling | PASS | PASS | `completed_scheduled` | `completed_scheduled` |
| B post-op, transfer connects | PASS | PASS | `completed_transferred` | `completed_transferred` |
| C post-op, transfer fails | **FAIL** | PASS | `escalation_failed` | `callback_pending` |
| D post-op, both fail | **FAIL** | PASS | `escalation_failed` | `escalation_failed` |
| **Totals** | **2/4** | **4/4** | 263s wall, 197s connected, $0.2955 | 183s wall, 118s connected, $0.1770 |

Dial ids: V1 A `598f49e5`, B `4adb3b93`, C `0607515f`, D `a96643f6`.
V2 A `a3e37862`, B `cf55bb5f`, C `d02456d4`, D `817c92b7`.

The two versions **agree** on the scenarios where nothing goes wrong and **diverge**
exactly where the practice policy matters. That isolates the design difference rather
than confounding it, which an earlier iteration of this comparison did not.

### What V1 does — the reported failure, reproduced

V1, scenario C, dial `0607515f`:

```
AI: "You're now connected with the triage nurse, and they'll take it from here."
```

| Evidence | Value |
|----------|-------|
| Transfer attempted | **failed** (line did not pick up) |
| Callback | **none** |
| Agent filed the call as | **resolved** |
| Derived status | `escalation_failed`, severity 4 |
| Promise mismatch | **true** |

A caller reporting a bleeding surgical wound was told they were connected to a nurse, and
the call was signed off as resolved. Nothing reached anyone. This is the practice
manager's complaint, word for word.

The backend caught it regardless of what the flow did: the derived status is driven by the
absence of a connected transfer session and the absence of a callback row, and the
unmatched promise is flagged separately.

V1's failing metrics name the fault precisely: `required_executions_present` (no callback),
`fallback_correct` (no escalation), `promise_consistent` (claimed a transfer that failed),
`disposition_truthful` (filed `resolved`), `disclosure_present` (never told the caller).

### What V2 changes

V2 never speaks about an outcome before it has one. Every closing line sits downstream of
the function whose result it describes and reads that result literally. On C, dial
`d02456d4`:

```
AI: "I could not reach the nurse, so a nurse will call you back.
     If this gets worse, please call the office or emergency services."
```

On D, dial `817c92b7`:

```
AI: "I could not reach the nurse or arrange a callback.
     Please call the office directly now, or emergency services..."
```

More importantly, **V2's escalation does not depend on the model at all.** The flow always
requests a callback after a transfer attempt, and the backend decides whether one is
warranted from the persisted transfer result. Even if the wording drifted, the callback
would still exist.

### What improved, what did not, what surprised

- **Improved.** Post-operative handling end to end: 0/2 to 2/2 on the failure scenarios.
  `promise_consistent` went from failing on every post-operative call to passing on all.
- **Unchanged.** Routine scheduling passes on both. V2's rework did not regress it.
- **Regressed.** Nothing measured. V2 makes one extra function call per post-operative
  call (`create_callback` even when unnecessary), which the backend answers
  `not_applicable`. One extra round trip for a guarantee that does not depend on the model.
- **Surprised me.** V1 is *cheaper to be wrong about* than to be right: its broken calls
  ran longer (197s connected vs 118s) because a flow that does not know when it has
  finished keeps talking. Worse safety and higher cost, together.

### What this cannot establish

Four scenarios, one run each per version, on synthetic audio, is not a prevalence estimate
and says nothing about production rates. The model runs at its default temperature because
any lower setting makes the agent mute (`INVESTIGATIONS.md` INV-3), so run-to-run variance
is higher than intended. See the flakiness note below.

---

## Experiment 2 — Evaluation efficiency

Same scenario set, same frozen version `dfc9502a-073c-42f0-b8f2-77afe4a35123`, same
metrics, same measurement code. Cold cache; nothing reused from the naive run.

### Naive baseline

Run `febdde6d-33a7-40e1-a18b-f530bbe6e65a`. Every scenario gets a full browser voice call,
sequential, no filtering.

| Scenario | Mode | Connected | Cost | Result |
|----------|------|-----------|------|--------|
| A | voice | 25s | $0.0375 | PASS |
| B | voice | 36s | $0.0540 | PASS |
| C | voice | 29s | $0.0435 | PASS |
| D | voice | 28s | $0.0420 | PASS |
| **Total** | | **118s** | **$0.1770** | 4/4, 183s wall-clock |

### Optimised run

Run `88643fe6-9378-4ab7-a8c9-7fbfdd56605d`.

| Scenario | Mode | Why this mode | Connected | Cost | Result |
|----------|------|---------------|-----------|------|--------|
| structural preflight | lint | gates the rest; fails fast on a flow that cannot speak truthfully | 0.0012s | $0 | PASS |
| A | replay | no failure branch on this path | 0s | $0 | PASS |
| B | replay | same | 0s | $0 | PASS |
| C | **voice** | high-risk transfer and callback path | 30s | $0.0450 | PASS |
| D | **voice** | high-risk, and the subtle double failure | 29s | $0.0435 | FAIL¹ |
| **Total** | | | **59s** | **$0.0885** | 3/4, 156s wall-clock |

### Measured savings

| Measure | Naive | Optimised | Absolute | Percent |
|---------|-------|-----------|----------|---------|
| Wall-clock | 183s | 156s | −27s | **−14.8%** |
| Connected seconds | 118s | 59s | −59s | **−50.0%** |
| Dollars (estimate) | $0.1770 | $0.0885 | −$0.0885 | **−50.0%** |
| Voice calls | 4 | 2 | −2 | −50% |

Both dimensions improved. Wall-clock falls by far less than dollars because the fixed
overhead — browser startup, dial creation, polling for the finalised dial record — is
unchanged for the two scenarios that still make calls, and replay still costs real seconds
against a hosted database.

**Parallelism contributes nothing.** This workspace permits one concurrent dial
(`500: Limit of 1 concurrent dials reached`), so both runs are fully sequential. The saving
comes entirely from making fewer calls.

### Coverage given up

- **Speech recognition on the routine path.** A and B no longer exercise it. This is a real
  loss: recognition mangling the caller's words was a genuine failure during development
  and only a voice call exposed it.
- **Whether the agent invokes the scheduler at all by voice.** Replay posts the function
  call itself, so it proves the backend and the recorded behaviour, not the live decision.
- **Turn-taking and latency on the routine path.**
- **Wording regressions on the scheduling confirmation.** The structural check verifies the
  node reads `{{node.book.status}}`, not what the agent says.

What the optimised run still covers in full: both high-risk paths end to end on real voice,
the complete evidence chain for every scenario, and every deterministic state metric.

### Disagreement between cheap checks and voice runs

| Scenario | Naive (voice) | Optimised (replay) | Agree? |
|----------|---------------|--------------------|--------|
| A | PASS `completed_scheduled` | PASS `completed_scheduled` | yes |
| B | PASS `completed_transferred` | PASS `completed_transferred` | yes |

No disagreement, which is a weak result rather than a reassuring one: two scenarios, one
run each, both already passing. It shows replay does not contradict voice. It does not show
replay would catch a voice-only regression, and it would not.

### Honest reading

The saving is real and measured, but small in absolute terms: $0.09 and 27 seconds on a
four-scenario suite. The strategy matters at scale, where replay and structural checks stay
near-free as scenarios are added while voice cost grows linearly.

---

## ¹ The one unstable metric, reported rather than hidden

Scenario D's `disclosure_present` — whether the agent mentions **both** the transfer failure
and the callback failure — is the only metric in the suite that varies run to run.

**Across the four runs since the closing line was shortened: 2 passed, 2 failed.**
(dials `682b1c74` PASS, `817c92b7` PASS, `a96643f6` FAIL, `e905460a` FAIL.)

Every one of those calls had **identical, correct action state**: transfer failed, callback
failed, callback queue empty, `escalation_failed` at severity 4, staff action required. Only
whether the sentence survived to the end of the call varied.

Root cause, established in `INVESTIGATIONS.md`: Vogent tears the call down while the agent
is still speaking, at a point that varies. Two independent transcript sources agree on where
the speech stopped, which rules out capture error. Mitigated by putting both required facts
in the first short sentence; not eliminated.

**This is the single most useful result in the suite**, because it is a controlled
demonstration of the project's central claim. The evidence that decides whether a
post-operative caller gets a nurse has been correct on every run. The evidence about what
the agent *said* is the only thing that wobbles. A suite that scored on transcripts would
call this agent unreliable half the time; a suite that scores on system state knows it is not.
