# Submission Checklist

Maps `ASSIGNMENT.md` deliverables to files and artifacts. Tick only with evidence in the repo.
Last verified 2026-09-19 by running each gate.

| # | Deliverable | Where | Done |
|---|-------------|-------|------|
| 1 | Two-minute setup and run commands | `README.md`, `SUBMISSION.md §1` | ☑ |
| 2 | End-to-end trace: scenario → dial → functions → DB → evaluator → UI | `SUBMISSION.md §2`, `artifacts/v2/febdde6d.../C_*/`, screens in `artifacts/ui/` | ☑ |
| 3 | Initial plan + practice-manager update | `docs/PROJECT_PLAN.md §1`, `docs/MANAGER_UPDATE.md` | ☑ |
| 4 | Time log ≤ 16 h | `TIME_LOG.md` — entries for phases 4 to 10 still to be added by the candidate | ☐ |
| 5 | Works / mocked / incomplete | `SUBMISSION.md §5` (mirrors `ARCHITECTURE.md §11`) | ☑ |
| 6 | Scenarios, baseline and optimized artifacts, per-case outcomes, time and dollar comparison | `evals/scenarios/`, `artifacts/efficiency/`, `SUBMISSION.md §6` | ☑ |
| 7 | AWS design, IaC, job evidence, teardown | `docs/ASYNC_INFRA_PLAN.md`, `infra/terraform/`, `artifacts/worker/` | ☑ |
| 8 | Flow export, agent/version and dial IDs, replay | `vogent/export/` (pinned to the versions that ran), `SUBMISSION.md §8`, `make replay` | ☑ |
| 9 | Security, privacy, reliability, production risks | `docs/RISKS.md`, `SUBMISSION.md §9` | ☑ |
| 10 | AI usage and personal verification | `SUBMISSION.md §10` | ☑ |
| 11 | Next steps | `SUBMISSION.md §11` | ☑ |
| — | Walkthrough video ≤ 8 min, single take | link in `SUBMISSION.md` | ☐ |

## Evidence gates (from the priority directive)

- ☑ Real voice run exists for A, B, C, D on V1 and on V2 (dial IDs in `SUBMISSION.md`)
- ☑ Scenario D (double failure) exists and was run on voice
- ☑ `derive_status` unit tests cover every scenario and the edge cases in `DATA_MODEL.md §5`
- ☑ Promise and action are separate in schema, API, UI
- ☑ At least one entry in `docs/INVESTIGATIONS.md` with before/after dial IDs
- ☑ Naive baseline measured (wall-clock, seconds, dollars, label) — `artifacts/efficiency/baseline/`
- ☑ Optimized run measured the same way — `artifacts/efficiency/optimized/`
- ☑ Coverage loss and disagreement table written
- ☑ C and D on voice in the optimized run
- ☑ Worker success and DLQ evidence — `artifacts/worker/`
- ☑ `terraform validate` output saved
- ☑ No secrets anywhere in the repo (`make secret-scan`)
