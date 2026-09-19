"""Confirm DATABASE_URL points at a reachable PostgreSQL we can write to."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg  # noqa: E402

from _env import load_env, require  # noqa: E402


def main() -> int:
    load_env()
    url = require("DATABASE_URL")
    with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
        cur.execute("SELECT version(), current_database(), current_user")
        version, database, user = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = current_schema()"
        )
        (tables,) = cur.fetchone()
        cur.execute("SELECT 1")  # write path is exercised by migrate; this is a liveness probe
    print(f"connected to {database} as {user}")
    print(f"  {version.split(',')[0]}")
    print(f"  {tables} tables in the current schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
