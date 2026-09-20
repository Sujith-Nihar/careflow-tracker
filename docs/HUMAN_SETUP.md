# Setup

Two paths. **A** needs nothing but a database and runs the whole system, including the
evaluation suite, the worker and the AWS definition. **B** adds the Vogent workspace and a
tunnel, and is only needed to place new voice calls; the calls behind the reported results
are already saved under `artifacts/`.

Secrets live in `.env` (git-ignored). The names below match `.env.example`.

---

## A. Reviewer path — no credentials, no cost

### Prerequisites

| Tool | Check | Notes |
|------|-------|-------|
| Python 3.12+ | `python3 --version` | prefers a `python3.12` binary, else `python3`; refuses anything older |
| Node 22 + npm | `node --version` | for the dashboard |
| PostgreSQL | either option below | Docker needs the daemon running |
| Terraform | `terraform version` | only for `make tf-validate` |

### Steps

```bash
cp .env.example .env
```

**1. A database.** Either start the bundled one:

```bash
docker compose up -d db
```

That container's user, password and database are all `careflow`, on port 5432; build
`DATABASE_URL` from those. Or point `DATABASE_URL` at any PostgreSQL 16 you already have.
Supabase works; prefer the direct connection on port 5432, or the session pooler if your
network is IPv4-only. Avoid the transaction pooler on 6543 — it does not hold a session and
breaks the schema search path.
Tests run in a `careflow_test` schema inside that same database, so there is no second URL.

**2. Two organization tokens.** Any two different values:

```bash
echo "CAREFLOW_DEMO_ORG_FUNCTION_TOKEN=$(openssl rand -hex 24)"
echo "CAREFLOW_DEMO_ORG_WEBHOOK_TOKEN=$(openssl rand -hex 24)"
```

Paste both into `.env`. `make seed` refuses to run if they are missing or identical.

**3. Install, migrate, seed:**

```bash
make setup
make migrate          # the public schema
make migrate-test     # the careflow_test schema, or `make test` silently skips 35 db tests
make seed
```

`make seed` prints the two practice ids. **Put the demo one on the existing
`DEMO_ORGANIZATION_ID=` line in `.env`** — the dashboard reads it server-side and returns 401
without it. Fill the blank line rather than appending a second copy: the loader takes the first
occurrence of a key and ignores later ones.

**4. Run it:**

```bash
make api                      # evidence API on :5055
make ui-install && make ui    # dashboard on :3000
```

Port 5055, not 5000: macOS AirPlay Receiver occupies 5000.

### Confirm it works

```bash
make db-check      # database reachable
make test          # backend tests against real PostgreSQL
make replay        # all five scenarios end to end, no voice, no cost
make structural    # flow lint: V1 fails five checks, V2 passes
make worker-demo   # queue, worker, poisoned job, dead-letter queue
make tf-validate   # the AWS definition
make secret-scan   # nothing credential-shaped is tracked
```

None of these need Vogent or AWS credentials.

---

## B. Voice path — only to place new calls

Everything in this section is already done for the runs in `docs/RESULTS.md`; their dial ids,
transcripts and evidence are saved under `artifacts/`. Follow it only to dial again.

### 1. Vogent workspace

- Use the **isolated assignment workspace**, never a production one.
- Create a secret API key → `VOGENT_API_KEY`. Confirm with `make vogent-check`, which lists
  agents and prints no secrets.
- Browser calls (Web SDK) must be enabled for the workspace.
- Budget roughly $3–5 for ~25 short calls at the standard-voice rate.

### 2. Publish the functions and flows

```bash
.venv/bin/python vogent/scripts/sync_functions.py   # creates/updates the four API functions
.venv/bin/python vogent/scripts/sync_flows.py       # publishes the V1 and V2 versioned prompts
```

`sync_functions.py` injects `CAREFLOW_DEMO_ORG_FUNCTION_TOKEN` as the `X-CareFlow-Token`
header value. `sync_flows.py` writes the resulting ids to `vogent/ids.json` (git-ignored)
and prints them; copy `VOGENT_AGENT_ID`, `VOGENT_V1_VERSIONED_PROMPT_ID` and
`VOGENT_V2_VERSIONED_PROMPT_ID` into `.env`.

`vogent/scripts/export_flows.py` writes `vogent/export/` — the two versions the reported runs
actually used, pinned by id, with header values redacted.

### 3. A public URL Vogent can reach

Vogent posts function calls to the backend, so it needs a reachable URL.

- ngrok with a free static domain, so function URLs never change between restarts:
  `NGROK_AUTHTOKEN`, and `BACKEND_PUBLIC_URL=https://<your-domain>.ngrok-free.app`.
- `make tunnel` starts it. `curl $BACKEND_PUBLIC_URL/healthz` should return 200.
- Fallback: `cloudflared tunnel --url http://localhost:5055`, which gives a random URL, so
  re-run `sync_functions.py` after every restart.

### 4. Browser audio

```bash
make setup-evals     # Playwright plus its Chromium; not part of `make setup`
```

The harness launches Chromium with fake-media flags, so no microphone prompt appears. macOS
`say` generates the synthetic caller audio and is built in.

### 5. Dial

```bash
make eval VERSION=v2                      # naive baseline: one voice call per scenario
make eval VERSION=v2 STRATEGY=optimized   # risk-based mix
make eval VERSION=v1                      # the baseline flow, for comparison
```

---

## C. AWS — not required

No AWS credentials are needed and nothing was deployed. `make tf-validate` checks the
definition locally. If a sandbox is available, set a standard `AWS_PROFILE` and follow
`ASYNC_INFRA_PLAN.md`; never use production infrastructure.
