# Kyron Medical — Full-Stack Take-Home (assignment, condensed copy; the original brief is the source of truth)

## Stabilize and Ship a Healthcare Voice-Agent Workflow

**Timebox:** 48-hour submission window; no more than 16 active working hours. Keep a coarse time log by
workstream, stop at 16 hours, submit what you have. Incomplete submissions are expected; prioritization,
whether the finished path genuinely works, and explanation of decisions are what matter.

**Approach:** Start from a blank repository. Optimize for a narrow, trustworthy vertical slice. Use AI
tools; include what was delegated to AI, where its output was verified or rejected, one important
decision made yourself, one part you would be comfortable modifying in the follow-up.

**Situation (practice manager):** "We had several callers yesterday who said they needed urgent help or a
callback. Some calls show as 'resolved' even though no transfer or callback happened. Staff are opening
individual calls to work out what actually occurred. Can you fix the immediate issue and give us a
reliable way to see which calls still need attention? We also have to keep routine scheduling working."

Build three surfaces: (1) a Vogent flow-based voice agent invoking HTTP functions; (2) a Python/Flask
service implementing tools and receiving call events; (3) a React/Next.js operations dashboard backed by
PostgreSQL. Evaluation runs should execute asynchronously and be observable in AWS. Everything synthetic.

**Fictional practice policy (only clinical rule):**
- Routine appointment requests may use a simulated scheduler.
- A post-operative concern must be routed to a simulated live triage transfer.
- If that transfer fails or cannot be verified, create a simulated urgent callback request and tell the
  caller plainly that the transfer did not complete.
- A call is not resolved merely because the agent promised a transfer, callback, or appointment.
  Completion requires evidence from the function result and final simulated system state.
- Do not diagnose or invent clinical rules. Unsupported/uncertain → explain the limitation, route to a human.

**Required outcome:** one inspectable path: synthetic caller audio → Vogent flow agent → Python
function/event handling → persisted state → automated evaluation → staff-visible result in React.
Cover one routine scheduling case, one post-op concern with a transfer attempt, one failure case where
promise and action differ. Core path must include executed end-to-end voice evaluations in the isolated
Vogent workspace via browser/web calls with synthetic audio (no telephone calls). Replay, transcript
counterfactuals, and structural checks do not replace voice runs. Save dial IDs, agent/version IDs,
timestamps, traces, function results, final state. Never publish workspace credentials.
React/TypeScript (Next.js preferred), Python (Flask preferred), PostgreSQL preferred (SQLite acceptable).

**Core expectations:**
1. Triage: short plan (failure model, verify first, smallest outcome, three priorities + deferrals,
   evidence that would change plan, questions). Plain-language update to the practice manager.
2. Safer, inspectable voice workflow: real flow agent in Vogent; flow export or reproducible description
   (nodes, transitions, functions, version); determine from evidence, not transcript, whether the promised
   action occurred (request/response data, event order, final state, retries, partial failures).
3. Backend boundary: handle Vogent-style function requests; idempotency/duplicates; tenant isolation;
   timeouts/retries/failed downstream actions; truthful status derivation; validation of string payloads;
   logs without sensitive data. Minimal simulation, explicit boundary.
4. Staff experience: which calls need human action; what the agent promised; what actually occurred; why
   this status; what failed and what to do next. Persisted data, investigation workflow over big dashboard.
5. Evaluate a change: run a reusable e2e eval suite (scheduling, post-op transfer, failed transfer/callback,
   one subtle failure). Each case: caller goal, expected behavior, authoritative action-state evidence,
   pass/fail. At least one deterministic state-based metric. Compare two agent behaviors with real Vogent
   runs for both; state improvements, regressions, what the suite cannot establish. Investigate one failure
   or surprise. Transcript is not proof; sample is not prevalence.
6. Measure and improve eval runtime and cost: naive run (each scenario a full sequential voice call);
   record wall-clock, connected seconds, dollars, other metered services; preserve raw measurements and
   pricing evidence; distinguish billed from estimated. Then an improved approach on the same scenarios
   and frozen version with measured savings in both time and dollars; do not reuse naive results for free;
   show which scenarios keep voice, which use cheap checks, what could be missed; keep high-risk
   transfer/callback path in real voice; compare outcomes and disagreements. Report honestly if not achievable.
7. AWS path: API/command → queue → worker → persisted result, with failure path and observable state.
   Small IaC. Demonstrate locally or in a sandbox: one success, one poisoned job to controlled failure,
   log correlation, least-privilege secrets, repeatable deploy/teardown. Live deploy optional.

**Additional (unranked):** multi-org without leakage; human review/override; deterministic replay and
versioning; duplicate/delayed/out-of-order events; auth/signature verification; accessibility; CI;
tradeoff comparisons; release gating/rollback/alarms/runbook; AWS sandbox deploy.

**Deliverables — `SUBMISSION.md`:** (1) two-minute setup + run commands; (2) e2e trace linked scenario →
final UI; (3) initial plan + manager update; (4) time log ≤ 16 h; (5) works / mocked / incomplete;
(6) scenarios, baseline and improved voice-run artifacts, per-case outcomes, time and cost comparison;
(7) AWS design, IaC, job evidence, teardown; (8) flow export/config, agent/version and dial IDs, replay;
(9) security/privacy/reliability/production risks; (10) AI usage and personal verification; (11) next steps.
Plus a single-take unedited walkthrough video ≤ 8 minutes.

**Evaluation focus:** prioritization; end-to-end ownership; correctness at boundaries; product judgment;
full-stack depth; real Vogent eval design/execution and measured optimization; persistence and AWS with
honest boundaries; security/privacy/ops judgment; empirical use of AI and evaluators; response to evidence;
communication; depth to debug and modify in follow-up.
