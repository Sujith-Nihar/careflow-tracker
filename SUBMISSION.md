# CareFlow Tracker — Submission

A voice-agent workflow where a call counts as handled only when persisted function and
downstream-system evidence says so, never because the agent said so.

Everything is synthetic. No real patients, phone numbers, EHRs or production systems.

---

## 1. Setup and run

```bash
cp .env.example .env          # fill in per docs/HUMAN_SETUP.md
make setup                    # python deps
make migrate && make seed     # schema + the two synthetic practices
make test                     # 90 backend tests against real PostgreSQL
make api                      # evidence API on :5055
make ui-install && make ui    # staff dashboard on :3000
```

No Vogent credentials needed for any of the above. To see the whole path without
spending anything:

```bash
make replay        # all five scenarios through the backend, no voice, no cost
make structural    # flow lint: V1 fails 5 checks, V2 passes
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

One scenario, followed all the way through. Scenario **C**: a caller reports a bleeding
surgical wound, the transfer to triage fails, an urgent callback must catch them.

| Stage | Evidence |
|-------|----------|
| Scenario definition | `evals/scenarios/C_postop_transfer_fail_callback.yaml` |
| Agent version | `0d16bb48-afe1-4b0c-9a7b-c155f5098fb0` (V2), exported at `vogent/export/v2.json` |
| Voice call | dial `01ff9f29-f2fc-4407-959a-d00e6d380c3c`, run `4d5286d0-f0c2-4906-8be0-57c140881af4` |
| Caller audio → recognition | `artifacts/efficiency/baseline/4d5286d0-.../C_.../dial.json` — "I had surgery on Tuesday. My surgery wound is bleeding." |
| Function calls | `transfer_triage` → `failed` (`no_answer`), then `create_callback` → `created` (urgent) |
| Simulated system state | transfer session `failed`; callback request `created`, priority `urgent` |
| What the agent said | "The transfer did not complete..." — a disclosure, not a claim |
| Derived status | `callback_pending`, severity 2, staff action required |
| Staff-visible reason | "The transfer to triage did not complete (no_answer). An urgent callback request was created and is still open." |
| In the dashboard | `/calls` → the call → side-by-side "agent said" vs "systems recorded" |

The same trace on the **optimised** run: dial `40a90b21-9150-47f8-8b6e-492abdb223a3`,
run `d7fc7213-97b1-45be-8602-2063a9c0041f`.

Contrast with **V1** on the same scenario: dial `8633e361-84bb-4998-a4d3-3d9e24e85235`.
The agent said "I'm connecting you to the triage nurse now." Action executions recorded:
**none**. Derived status `no_action_recorded` with the promise flagged as unmatched. That
is the reported failure, reproduced.

---

## 3. Plan and customer update

- Initial triage and plan: `docs/PROJECT_PLAN.md §1`
- Update for the practice manager: `docs/MANAGER_UPDATE.md`

---

## 4. Time log

`TIME_LOG.md`, maintained by hand.

---

## 5. What works, what is simulated, what is not built

**Works, verified by running it**

- Evidence model in PostgreSQL: 14 tables keeping caller intent, agent promise, requested
  action, attempted action, action result, downstream state and derived status separate.
- Flask boundary: four Vogent function endpoints, webhook ingestion, idempotency on
  repeat delivery, per-organization isolation, bounded validation of LLM-produced strings,
  structured logs with a field allow-list.
- Deterministic status derivation: one pure function, a documented decision table, 100%
  line coverage, and no path by which transcript text can produce a completed status.
- Two Vogent flow versions, published and exported, reproducible from the repo.
- Real browser voice evaluations: 28 archived runs, all four scenarios passing on V2.
- Replay suite covering all five scenarios with no voice and no cost.
- Both efficiency runs measured end to end.
- Staff dashboard on persisted data, with a working "callback completed" action.
- Async evaluation path: queue → worker → persisted run, with a poisoned job reaching the
  dead-letter queue and log correlation by `job_id`.
- Evaluation runs persisted as rows, not only files, sharing one id with their artifacts.
- 90 backend tests against a real database; `make lint` clean under a strict ruleset.

**Simulated, deliberately**

The scheduler, the triage transfer line and the callback queue are in-process simulators
driven by a fault profile registered against the dial before the call starts. The caller
is synthetic speech. Staff identity is a free-text string. There is no EHR, no telephony
and no real transfer; the boundary is `backend/app/simulators/`.

**Not built**

- **A live AWS deployment.** The async path runs locally and its AWS definition
  validates, but nothing has been applied to an account. See §7.
- **A judgment-based evaluator.** Optional in the brief; not attempted.
- **Authentication.** Organization isolation is enforced by shared-secret tokens and
  scoped queries; there is no user identity. See §9.

---

## 6. Evaluation

Scenario definitions: `evals/scenarios/*.yaml`. Full results with dial IDs, coverage
analysis and caveats: **`docs/RESULTS.md`**.

**Experiment 1 — agent quality**

| Scenario | V1 | V2 |
|----------|----|----|
| A routine scheduling | PASS | PASS |
| B post-op, transfer connects | FAIL | PASS |
| C post-op, transfer fails | FAIL | PASS |
| D post-op, both fail | FAIL | FAIL¹ |
| | 1/4 | 3/4 |

¹ D's action-state evidence was correct on every run; only the transcript-derived
`disclosure_present` metric failed, and it passed on an isolated re-run (dial `885c128d`)
and on the optimised run. This is model variance, discussed in `docs/RESULTS.md`.

V1's failures are over-determined, and `docs/RESULTS.md` says so rather than claiming a
cleaner result than the evidence supports.

**Experiment 2 — evaluation efficiency**, same frozen version, same scenarios

| Measure | Naive | Optimised | Saving |
|---------|-------|-----------|--------|
| Wall-clock | 285s | 198s | −30.5% |
| Connected seconds | 148s | 62s | −58.1% |
| Dollars (estimate) | $0.2220 | $0.0930 | −58.1% |
| Voice calls | 4 | 2 | −50% |

Both high-risk paths keep real voice. Coverage given up and the disagreement analysis are
in `docs/RESULTS.md` and are not favourable to the optimised run: no disagreement was
observed, but on two already-passing scenarios, which proves little.

All dollar figures are **CALCULATED ESTIMATE** from `aiDurationSeconds × $0.0015`
(docs.vogent.ai/platform-overview/billing, read 2026-09-18). None are billed charges.
No other metered service was used: speech synthesis is local, the tunnel is free tier.

**Investigations**: five, in `docs/INVESTIGATIONS.md`, each with before and after dial IDs.
The most consequential (INV-4) found that Vogent function nodes cannot branch on their own
result, which invalidated V2's original design and moved the escalation decision into the
backend — where it is now enforced from persisted state rather than by a language model.

---

## 7. AWS path

Design and reasoning: `docs/ASYNC_INFRA_PLAN.md`. Evidence: `artifacts/worker/`.

```bash
make worker-demo    # the whole path, locally, no AWS account
make tf-validate    # the AWS definition
```

**Demonstrated locally.** A job becomes a persisted `evaluation_runs` row with a case per
scenario. A poisoned job naming a scenario that does not exist is received three times,
fails identically each time with a named reason, and is carried to the dead-letter queue
by the redrive policy:

```
dead-letter queue: 1 message(s)
  job_id=job-b709bd5d1b  scenarios=Z_does_not_exist  receives=4
    find the logs with: grep '"job_id": "job-b709bd5d1b"' <worker log>
```

**Defined for AWS.** `infra/terraform/`: work queue and dead-letter queue with redrive
after three receives and SSE; separate execution and task IAM roles each scoped to named
resources; a Fargate task whose secrets are injected from SSM SecureStrings at start; a
log group with retention; an alarm on the dead-letter queue being non-empty; and outputs
including the Logs Insights query that traces one evaluation run. `terraform validate`
passes and `terraform fmt -check` is clean; the output is saved in
`artifacts/worker/terraform_validate.json`.

**Not deployed.** No AWS account was used. Applying it is untested beyond validation, and
no claim is made otherwise. Teardown is `terraform destroy`.

**Boundary worth naming.** The worker runs replay jobs only. A voice run needs a browser
and a Vogent workspace, which a headless container in a private subnet does not have.
The worker rejects any other mode rather than failing in production for a reason that was
predictable.

---

## 8. Vogent configuration

- Authored flows: `vogent/flows/v1.json`, `v2.json`, shared context in `_shared.json`
- Function definitions: `vogent/functions/*.json` (paths relative, secrets injected at sync)
- **Live export of what actually ran**: `vogent/export/` with header values redacted
- Sync and export scripts: `vogent/scripts/`
- Agent: `b3d8f0c2-c96e-4a37-b023-ce1d0d99a82d`
- Versions used for the reported runs: V1 `139c8c53-...`, V2 `0d16bb48-...`
- Dial IDs: §2 above and every `metrics.json` under `artifacts/`
- Local replay: `make replay`

Twelve places where the Vogent documentation and its actual behaviour differ are recorded
in `docs/VOGENT_PLAN.md §2a`, each with the symptom it caused.

---

## 9. Risks

Full register with mitigation status in `docs/RISKS.md`. The ones that matter most:

- **No authentication.** Organization isolation is real and tested (wrong token 401,
  agent/organization mismatch 403, cross-organization read 404), but there is no user
  identity, so "who closed this call" is a free-text string.
- **No request signing.** Vogent documents none, so function calls are authenticated by a
  per-organization shared secret over TLS. A leaked token would let someone write evidence
  against that practice.
- **De-duplication, not exactly-once.** Repeat delivery of an identical request on the same
  dial is collapsed and the repeat recorded. Nothing stronger is claimed.
- **Truthfulness is model-dependent.** The escalation itself is not: the backend creates
  the callback from persisted state. But whether the caller is *told* correctly depends on
  the agent following an instruction, and scenario D shows that occasionally fails.
- **Tunnel exposure.** While running, the backend is reachable by anyone with the URL.
  Function endpoints reject unauthenticated requests; the tunnel should be stopped when idle.
- **Small synthetic sample.** Four scenarios are not a prevalence estimate.

No claim of HIPAA compliance or production readiness is made.

---

## 10. How AI was used

This project was built with Claude Code as the primary implementer, with me directing
scope, priorities and design decisions.

**Delegated:** the bulk of implementation — schema, Flask endpoints, simulators, the
derivation function, the evaluation harness, the flow JSON, the dashboard — plus routine
debugging and documentation drafting.

**Verified or rejected.** Every claim about Vogent's behaviour was tested rather than
trusted, and that mattered: the documentation was wrong or silent on twelve points. Three
diagnoses were confidently wrong and were overturned by the next run — a question node was
blamed for silence caused by a temperature setting (INV-2 vs INV-3); a transition `field`
"fix" was a regression proved by an isolated probe; a transcript truncation was blamed on
read timing when the harness was cutting the agent off. In each case the correction came
from running an experiment, not from reasoning harder.

**My own decision.** Moving the escalation decision out of the conversation graph and into
the backend. When function-node branching turned out not to work, the obvious response was
to make the prompt try harder. Instead the backend now decides whether a fallback is
warranted from the persisted transfer result. The flow cannot be talked out of escalating,
because it no longer makes that choice. That is the single change that makes the system's
central guarantee independent of the model.

**Comfortable modifying live.** `backend/app/domain/derive_status.py` and its decision
table. It is pure, fully covered, and every rule maps to a row in `docs/DATA_MODEL.md §5`.

---

## 11. What I would do next

1. **Isolate the V1 comparison.** V1's failures are over-determined. Moving its promise into
   the function's lifecycle message would test the design flaw alone.
2. **Repeat runs per scenario.** Scenario D is flaky on one transcript metric. Three runs per
   scenario with a reported pass rate would replace a coin-flip with a measurement.
3. **Alerting on `escalation_failed`.** The worst state in the system currently waits to be
   noticed on a screen.
4. **Callback ageing.** The system knows a callback is owed, not that it has been owed for hours.
5. **Widen the transcript rules or replace them.** They are regexes tuned to phrasings I
   anticipated. A second model scoring truthfulness, checked against hand-labelled traces,
   would generalise better — and the brief's optional rubric-based evaluator is exactly that.
