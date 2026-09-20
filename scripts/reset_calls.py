"""Delete every call and evaluation record, keeping the practices themselves.

Used to clear development traffic before a clean demonstration run. Organizations
and agent registrations survive, so tokens and the dashboard's organization id stay
valid and nothing has to be re-seeded.

Artifacts on disk are untouched: they are the permanent record of a run, and the
database is a queryable view of it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg
from _env import load_env, require

# Order matters only for readability; every table below cascades from calls or runs.
TABLES = [
    "staff_actions",
    "agent_statements",
    "appointments",
    "transfer_sessions",
    "callback_requests",
    "action_executions",
    "evaluation_cases",
    "evaluation_runs",
    "vogent_events",
    "fault_profiles",
    "calls",
]

KEPT = ["organizations", "agent_registrations"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear call and evaluation data")
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    parser.add_argument("--schema", default="public")
    args = parser.parse_args()

    load_env()
    url = require("DATABASE_URL")

    with psycopg.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {args.schema}, public")
            cur.execute("SELECT count(*) FROM calls")
            calls = cur.fetchone()[0]

        if not args.yes:
            print(f"About to delete {calls} call(s) and everything hanging off them.")
            print(f"Keeping: {', '.join(KEPT)}")
            if input("Type 'yes' to continue: ").strip().lower() != "yes":
                print("cancelled")
                return 1

        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {args.schema}, public")
            cur.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {args.schema}, public")
            cur.execute("SELECT count(*) FROM calls")
            remaining = cur.fetchone()[0]
            cur.execute("SELECT slug FROM organizations ORDER BY slug")
            orgs = [r[0] for r in cur.fetchall()]

    print(f"deleted {calls} call(s); {remaining} remain")
    print(f"practices kept: {', '.join(orgs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
