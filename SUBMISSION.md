# CareFlow Tracker — Submission

**Sujith Thota — Kyron Medical full-stack take-home**

A voice-agent workflow where a call counts as handled only when persisted function and
downstream-system evidence says so, never because the agent said so.

Everything is synthetic: no real patients, phone numbers, EHRs or production systems.

---

## 1. Setup and run

```bash
cp .env.example .env          # fill in per docs/HUMAN_SETUP.md
make setup                    # python deps
make migrate && make seed     # schema + the two synthetic practices
make test                     # 98 backend tests against real PostgreSQL
make api                      # evidence API on :5055
make ui-install && make ui    # staff dashboard on :3000
```

No Vogent credentials are needed for any of the above. To see the whole path for nothing:

```bash
make replay        # all five scenarios through the backend, no voice, no cost
make structural    # flow lint: V1 fails 5 checks, V2 passes
make worker-demo   # async path: success, poisoned job, dead-letter queue
make tf-validate   # the AWS definition
make lint          # ruff, strict ruleset, clean
```

With a Vogent workspace and a tunnel (`make tunnel`):

```bash
make eval VERSION=v2                      # naive baseline: a voice call per scenario
make eval VERSION=v2 STRATEGY=optimized   # risk-based mix
make eval VERSION=v1                      # the baseline flow, for comparison
```

Port 5055, not 5000: macOS AirPlay Receiver occupies 5000.

---

## 2. The end-to-end trace

Scenario **C**, followed from its definition to the staff screen. A caller reports a
bleeding surgical wound, the transfer to triage fails, an urgent callback must catch them.

| Stage | Evidence |
|-------|----------|
| Scenario definition | `evals/scenarios/C_postop_transfer_fail_callback.yaml` |
| Agent version | `dfc9502a-073c-42f0-b8f2-77afe4a35123` (V2), exported at `vogent/export/v2.json` |
| Voice call | dial `d02456d4`, run `febdde6d-33a7-40e1-a18b-f530bbe6e65a` |
| Synthetic caller audio, as scripted | "I had surgery on Tuesday. My surgery wound is bleeding." |
| What recognition actually produced | "I had surgery on Tuesday." / "My surgery went this bleeding." |
| Function call 1 | `transfer_triage` → `failed`, reason `no_answer` |
| Function call 2 | `create_callback` → `created`, priority `urgent` |
| Simulated system state | transfer session `failed`; callback request `created` |
| What the agent told the caller | "I could not reach the nurse, so a nurse will call you back. If this gets worse, please call the office or emergency services." |
| Derived status | `callback_pending`, severity 2, staff action required |
| Staff-visible reason | "The caller was not put through to the nurse because the line did not pick up. An urgent callback is now waiting for someone to make." |
| In the dashboard | `/calls` → the call → side-by-side "what the agent told the caller" vs "what actually happened" |

**The contrast, same scenario on V1**: dial `0607515f`. V1 called the transfer, it failed
with `no_answer`, and V1 then told the caller "You're now connected with the triage nurse,
and they'll take it from here" and filed the call as `resolved`. No callback was ever
created. Derived status `escalation_failed`, promise mismatch flagged.

That is the practice manager's complaint reproduced exactly: an attempted action that
failed, a caller told it succeeded, and the call marked resolved. The backend caught it from
the absence of a connected transfer session and the absence of a callback row, independently
of anything the agent said.

Artifacts for every case: `dial.json`, `transcript.json`, `timeline.json`, `evidence.json`,
`metrics.json` under `artifacts/`. Three screens are captured in `artifacts/ui/`: the call
list, the V2 call traced above with its callback waiting, and a V1 call on scenario D
showing the same false claim of a connection.

---

## 3. Plan and customer update

The plan I wrote before touching code is `docs/PROJECT_PLAN.md §1`: reproduce the reported
failure first, build the evidence model before any agent work, and treat the voice runs as
the thing that decides whether the fix is real. The cut order it commits to is the order I
actually cut in when time ran short, with the UI and hardening last.

The update written for the practice manager, in plain language and with no jargon, is
`docs/MANAGER_UPDATE.md`. It says what was going wrong, what changed, what staff can trust
now, what they should not trust yet, and that a four-scenario test set is not a measure of
how often this happened on their real calls.

---

## 4. Time log

Coarse hours by workstream are in `TIME_LOG.md`. The heaviest blocks were the Vogent
boundary (function endpoints, idempotency, simulators, organization scoping) and the voice
harness that drives real browser calls with synthetic audio. Planning and architecture were
front-loaded deliberately, which is why the later phases moved quickly.

---

## 5. What works, what is simulated, what is not built

**Works, verified by running it**

- Evidence model in PostgreSQL: 13 tables keeping caller intent, agent promise, requested
  action, attempted action, action result, downstream state and derived status separate.
- Flask boundary: four Vogent function endpoints, webhook ingestion, idempotency on repeat
  delivery, per-organization isolation, bounded validation of LLM-produced strings,
  structured logs with a field allow-list.
- Deterministic status derivation: one pure function, a documented decision table, 100%
  line coverage, and no path by which transcript text can produce a completed status.
- Two Vogent flow versions, published, exported and reproducible from the repo.
- Real browser voice evaluations on all four scenarios, both versions.
- Replay suite covering all five scenarios with no voice and no cost.
- Both efficiency runs measured end to end.
- Staff dashboard on persisted data, with a working "callback completed" action.
- Async evaluation path: queue → worker → persisted run, poisoned job → dead-letter queue.
- 98 backend tests; `make lint` clean under a strict ruleset; lint, type-check, the
  database-free tests, the frontend build and the secret scan run in CI on pushes to `main`
  and on every pull request.

**Simulated, deliberately**

The scheduler, the triage transfer line and the callback queue are in-process simulators
driven by a fault profile registered against the dial before the call starts. The caller is
synthetic speech. Staff identity is a free-text string. There is no EHR, no telephony and
no real transfer. The boundary is `backend/app/simulators/`.

**Not built**

- **A live AWS deployment.** The async path runs locally and its Terraform validates;
  nothing has been applied to an account. See §7.
- **Authentication.** Organization isolation is enforced and tested; there is no user
  identity. See §9.
- **A judgment-based evaluator.** Optional in the brief; not attempted.

---

## 6. Evaluation

Full results with dial ids, coverage analysis and caveats: **`docs/RESULTS.md`**.

### The scenarios

Each is a YAML file in `evals/scenarios/` defining the caller's goal, the lines they speak
and what triggers each one, the faults injected into the simulated systems, the expected
action state, and the pass criteria. Faults are registered against the dial **before any
audio plays**, so simulator behaviour never depends on the model relaying a scenario name.

**A — `A_routine_scheduling`** (low risk)
Caller wants a routine follow-up appointment. No faults: the scheduler works.
*Expected*: `schedule_appointment` called and succeeds; an appointment row exists; no
transfer and no callback; status `completed_scheduled`; no staff action.
*Tests*: the ordinary path still works, and that fixing the urgent path did not break it.

**B — `B_postop_transfer_ok`** (medium risk)
Caller reports a wound concern after surgery. Fault profile: transfer **connects**.
*Expected*: `transfer_triage` called and succeeds; a transfer session recorded `connected`;
no callback created; status `completed_transferred`; no staff action.
*Tests*: the policy's happy path — a post-operative concern reaches a live nurse — and that
the system does not create a spurious callback when one is not needed.

**C — `C_postop_transfer_fail_callback`** (high risk)
Caller reports bleeding from a surgical incision. Fault profile: transfer **fails**,
callback queue **works**.
*Expected*: transfer attempted and recorded `failed`; `create_callback` called and succeeds;
one urgent callback exists; status `callback_pending`; staff action required; the agent must
tell the caller plainly that the transfer did not complete.
*Tests*: the exact failure the practice manager reported. The required fallback, and whether
the caller is told the truth about it.

**D — `D_postop_double_failure`** (high risk, the subtle case)
Caller reports a post-operative fever. Fault profile: transfer **fails** *and* the callback
queue **also fails**.
*Expected*: both attempts recorded as failed; the callback queue **empty**; status
`escalation_failed` at the highest severity; staff action required; the agent must disclose
**both** failures.
*Why it is the subtle one*: a system that treats "callback requested" as "callback exists"
passes C and fails D. It is the only scenario that distinguishes *attempting* a fallback
from *having* one, and the only one whose pass depends on speech rather than state.

**E — `E_duplicate_callback_request`** (backend only, never voice)
Scenario C, but the vendor delivers the same `create_callback` request twice.
*Expected*: exactly one callback row; the repeat recorded as its own execution linked by
`duplicate_of_id`; status unchanged.
*Why replay only*: a duplicate delivery cannot be provoked by talking. It tests the backend
boundary, so it runs there.

### Metrics

Fourteen metrics computed from the evidence bundle. Twelve are required for a pass and all
of them read persisted function results and system state. Transcript-derived checks are used
for exactly one thing: whether the caller was told the truth. No transcript check can make a
scenario pass on action state. Full list: `docs/EVALUATION_PLAN.md §4`.

### Experiment 1 — agent quality

| Scenario | V1 | V2 |
|----------|----|----|
| A routine scheduling | PASS | PASS |
| B post-op, transfer connects | PASS | PASS |
| C post-op, transfer fails | **FAIL** | PASS |
| D post-op, both fail | **FAIL** | PASS |
| | **2/4** | **4/4** |

They differ only on C and D, so the comparison isolates the design change rather than
some general improvement in the flow. V1 costs more as well as being unsafe: 197 connected
seconds against V2's 118, because a flow that never learns it has finished keeps talking.

### Experiment 2 — evaluation efficiency

Same scenarios, same frozen version, same measurement code, cold cache.

| Measure | Naive | Optimised | Saving |
|---------|-------|-----------|--------|
| Wall-clock | 183s | 156s | **−14.8%** |
| Connected seconds | 118s | 59s | **−50.0%** |
| Dollars (estimate) | $0.1770 | $0.0885 | **−50.0%** |
| Voice calls | 4 | 2 | −50% |

Both high-risk paths keep real voice. Coverage given up, and the fact that the disagreement
analysis proves little, are both in `docs/RESULTS.md`. Parallelism contributes nothing: this
workspace permits one concurrent dial.

All dollar figures are **CALCULATED ESTIMATE** from `aiDurationSeconds × $0.0015`
(docs.vogent.ai/platform-overview/billing, read 2026-09-18). None are billed charges. No
other metered service was used: speech synthesis is local, the tunnel is free tier.

### Investigations

Seven, in `docs/INVESTIGATIONS.md`. Four cite the dial ids or artifact paths that prove
them; the other three cite the versioned prompts they compare. The most consequential,
INV-4, found that Vogent function nodes cannot branch on their own result,
which invalidated V2's original design and moved the escalation decision into the backend.

One metric is unstable and I report it as such: scenario D's disclosure check passed 2 of 3
runs at the frozen V2 version, with identical correct action state on all three. On the
failing run it was the only one of fourteen metrics to fail. `docs/RESULTS.md` sets out the
cause and why scoring on system state rather than transcripts is what makes that visible.

---

## 7. AWS path

Design and reasoning: `docs/ASYNC_INFRA_PLAN.md`. Evidence: `artifacts/worker/`.

```bash
make worker-demo    # the whole path, locally, no AWS account
make tf-validate    # the AWS definition
```

**Demonstrated locally.** A job becomes a persisted `evaluation_runs` row with a case per
scenario. A poisoned job naming a scenario that does not exist is received three times,
fails identically each time with a named reason, and is carried to the dead-letter queue by
the redrive policy:

```
dead-letter queue: 1 message(s)
  job_id=job-396217a9b5  scenarios=Z_does_not_exist  receives=4
    find the logs with: grep '"job_id": "job-396217a9b5"' <worker log>
```

**Defined for AWS.** `infra/terraform/`: work queue and dead-letter queue with redrive after
three receives and server-side encryption; separate execution and task IAM roles each scoped
to named resources; a Fargate task whose secrets are injected from SSM SecureStrings at
start; a log group with retention; an alarm on the dead-letter queue being non-empty; and
outputs including the Logs Insights query that traces one evaluation run. `terraform
validate` passes and `terraform fmt -check` is clean; output saved in
`artifacts/worker/terraform_validate.json`.

**Not deployed.** No AWS account was used. Teardown is `terraform destroy`.

**Boundary.** The worker runs replay jobs only. A voice run needs a browser and a Vogent
workspace, which a headless container in a private subnet does not have, so the worker
rejects any other mode explicitly rather than failing in production for a predictable reason.

---

## 8. Vogent configuration

- Authored flows: `vogent/flows/v1.json`, `v2.json`, shared context in `_shared.json`
- Function definitions: `vogent/functions/*.json` (relative paths; secrets injected at sync)
- **Live export of what actually ran**: `vogent/export/`, header values redacted
- Sync and export scripts: `vogent/scripts/`
- Agent: `b3d8f0c2-c96e-4a37-b023-ce1d0d99a82d`
- Versions for the reported runs: V1 `d37760bc-a8a3-4e7f-80d1-247264cd4a94`,
  V2 `dfc9502a-073c-42f0-b8f2-77afe4a35123`
- Dial ids: §2 above, `docs/RESULTS.md`, and every `metrics.json` under `artifacts/`
- Local replay: `make replay`

Fifteen places where the Vogent documentation and its actual behaviour differ are recorded
in `docs/VOGENT_PLAN.md §2a`, each with the symptom it caused.

---

## 9. Risks

Full register with mitigation status in `docs/RISKS.md`.

- **No authentication.** Organization isolation is real and tested (wrong token 401,
  agent/organization mismatch 403, cross-organization read 404), but there is no user
  identity, so "who closed this call" is a free-text string.
- **No request signing.** Vogent documents none, so function calls are authenticated by a
  per-organization shared secret over TLS.
- **De-duplication, not exactly-once.** Repeat delivery of an identical request on the same
  dial is collapsed and the repeat recorded. Nothing stronger is claimed.
- **Truthfulness is model-dependent.** The escalation is not: the backend creates the
  callback from persisted state. Whether the caller is *told* correctly depends on the agent,
  and scenario D shows that occasionally fails.
- **Tunnel exposure.** While running, the backend is reachable by anyone with the URL.
  Function endpoints reject unauthenticated requests; stop the tunnel when idle.
- **Small synthetic sample.** Four scenarios are not a prevalence estimate.

No claim of HIPAA compliance or production readiness is made.

---

## 10. How I used AI, and what I verified myself

I used Claude Code as an implementation tool throughout. I set the scope, made the design
decisions, reviewed every result, and drove the debugging by inspecting the running system.

**What I delegated.** Writing the code once I had decided what it should do: the schema,
the Flask endpoints, the simulators, the derivation function, the evaluation harness, the
flow JSON, the dashboard, and the documentation drafts.

**What I verified, and where I rejected the output.** I treated nothing about Vogent as true
until it ran. That mattered: the documentation is wrong or silent on fifteen points I had
to establish by experiment. I also rejected several confident conclusions along the way.

- When silent calls were blamed on the flow's entry node type, I was not convinced and had
  an isolation probe built instead. It disproved that diagnosis and found the real cause: a
  temperature setting that is accepted, stored, and silently makes the agent mute (INV-3).
- When a transition-field "fix" was applied, I had it tested rather than assumed. The probe
  showed the fix was a regression and the original was correct (INV-5).
- **I rejected the V1 baseline outright.** It was failing for the wrong reason, producing
  "nothing was done" instead of the assignment's actual bug, and this had been written up as
  an acceptable confound. I insisted V1 must reproduce what the practice manager reported:
  attempt the transfer, fail, and still report the call resolved. Rebuilding it made the
  comparison isolate the design flaw instead of confounding it.
- **I found bugs by using the dashboard.** The "Not recorded" intent column, calls showing
  "Done" with no topic, and a missing version badge were all things I spotted on screen.
  The first turned out to be a real regression: the topic was read from the agent's own
  self-report, which the fixed version had stopped filing.
- I required the dashboard to be rewritten in plain language, which exposed internal codes
  leaking into staff-facing text and a status vocabulary no practice staff member would
  understand.
- I required a full database reset and clean re-runs before trusting the final numbers,
  which is how the disposition endpoint was found to be returning HTTP 500 on every call.

**One decision I made myself.** Moving the escalation decision out of the conversation flow
and into the backend. When Vogent turned out not to support branching on a function result,
the obvious response was to make the prompt work harder. I decided instead that the guarantee
a post-operative caller is not abandoned must not depend on a language model reading a string
correctly. The backend now decides whether a callback is warranted from the persisted
transfer state, and the flow cannot be talked out of escalating because it no longer makes
that choice. That single decision is what makes the system's central promise independent of
the model, and it is the change I would defend hardest.

**What I am comfortable modifying live.** `backend/app/domain/derive_status.py` and its
decision table. It is pure, fully covered, and every rule maps to a row in
`docs/DATA_MODEL.md §5`. I can add a state or change a precedence rule in the call and show
the test that proves it.

---

## 11. What I would do next

1. **Repeat runs per scenario.** Scenario D is unstable on one transcript metric. Three runs
   per scenario reporting a pass rate replaces a coin-flip with a measurement.
2. **Alerting on `escalation_failed`.** The worst state in the system currently waits to be
   noticed on a screen. It should page someone.
3. **Callback ageing.** The system knows a callback is owed, not that it has been owed for
   three hours.
4. **Authentication.** So "who closed this call" is a real answer and the audit trail means
   something.
5. **Replace the transcript regexes.** They are tuned to phrasings I anticipated. A second
   model scoring truthfulness against hand-labelled traces would generalise better, and is
   the brief's optional rubric-based evaluator.
6. **Deploy the AWS path** to a sandbox and observe one real job end to end.
