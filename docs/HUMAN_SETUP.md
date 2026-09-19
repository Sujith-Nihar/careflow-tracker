# Human Setup Checklist

Everything the candidate must provide or do by hand so implementation can run without interruption.
Secrets go in `.env` (git-ignored); the names below match `.env.example`.

## A. Local tools — REQUIRED NOW

| Item | Check | Status on 2026-09-18 |
|------|-------|----------------------|
| Python 3.12 | `python3.12 --version` | present (3.12.13) |
| Node 22 + npm | `node --version` | present (22.13.1) |
| Playwright Chromium | installed by `make setup` (`playwright install chromium`) | pending |
| macOS `say` | `say -v '?' \| head` | macOS built-in |
| Docker | only if choosing local Postgres or ElasticMQ fallback | installed, daemon not running (optional) |
| Terraform CLI | only for `terraform validate` in Phase 9 (`brew install terraform`) | missing — REQUIRED LATER |
| ngrok CLI | `brew install ngrok` | unknown — REQUIRED NOW |

## B. PostgreSQL — REQUIRED NOW

Choice: **Supabase project used purely as managed Postgres** (no Supabase auth/storage/edge features).
Alternative: `docker compose up -d db` (compose file provided for reviewers).

- [ ] Create a Supabase project dedicated to this take-home (do not reuse another project's database).
- [ ] Copy the direct connection string (port 5432, not the pooler, so `pg_notify`/DDL behave normally) →
      `DATABASE_URL`.
- [ ] Integration tests use schema `careflow_test` in the same database → `TEST_DATABASE_URL` is the
      same URL with `?options=-csearch_path%3Dcareflow_test` (created by `make migrate-test`).
- [ ] Confirm connectivity: `make db-check`.

## C. Vogent — REQUIRED NOW

- [ ] Access to the **isolated assignment workspace** confirmed (never a production workspace).
- [ ] Secret API key created → `VOGENT_API_KEY`. Confirm with `make vogent-check` (lists agents).
- [ ] Browser calls enabled for the workspace (Web SDK); confirm one manual call from the Vogent UI works.
- [ ] Credit or billing enabled for ≈ 25 short calls (≈ $3–5 at the standard-voice rate).
- [ ] After Phase 4 sync: `VOGENT_AGENT_ID`, `VOGENT_V1_VERSIONED_PROMPT_ID`, `VOGENT_V2_VERSIONED_PROMPT_ID`
      (written by `vogent/scripts/sync.py`; copy into `.env`).
- [ ] Function header value: generate `CAREFLOW_DEMO_ORG_FUNCTION_TOKEN` (`openssl rand -hex 24`) and
      paste it as the `X-CareFlow-Token` header value when `sync.py` prints the instruction.

## D. Public backend URL — REQUIRED NOW

Vogent must reach Flask. Choice: **ngrok with a free static domain** so function URLs never change.
- [ ] ngrok account, auth token → `NGROK_AUTHTOKEN`; claim the free static domain in the ngrok dashboard.
- [ ] `BACKEND_PUBLIC_URL=https://<your-static-domain>.ngrok-free.app`.
- [ ] `make tunnel` starts it; `curl $BACKEND_PUBLIC_URL/healthz` returns 200.
Fallback: `cloudflared tunnel --url http://localhost:5000` (random URL; re-run `sync.py` after each restart).

## E. Browser audio — REQUIRED for Phase 5

- [ ] Chromium launched by Playwright is allowed to use fake media (flags handle it; no OS prompt expected).
- [ ] For the manual-mic fallback only: macOS microphone permission for Chromium.

## F. AWS — OPTIONAL (not required)

No AWS credentials are needed. Terraform is validated locally. If a sandbox is available later, set
standard `AWS_PROFILE` and follow `ASYNC_INFRA_PLAN.md`; never use production infrastructure.

## G. Decisions only the candidate can make — REQUIRED before Phase 4

- [ ] Confirm `report_disposition` stays as the fourth function (`DECISIONS.md` D6).
- [ ] Confirm the scenario D choice (transfer fails and callback fails) as the subtle case.
- [ ] Confirm staff "mark callback completed" stays in scope (cut candidate #2).
