"""Confirm DATABASE_URL points at a reachable PostgreSQL we can write to."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg  # noqa: E402

from _env import fail, load_env, require  # noqa: E402


def main() -> int:
    load_env()
    url = require("DATABASE_URL")
    try:
        return _probe(url)
    except psycopg.OperationalError as exc:
        # Never surface the DSN: a driver error can echo fragments of the password.
        fail(f"could not connect to the database: {_sanitize(str(exc), url)}")
        return 1


def _sanitize(message: str, url: str) -> str:
    """Strip anything derived from the credential out of a driver message."""
    userinfo = url.split("//", 1)[-1].rsplit("@", 1)[0] if "@" in url else ""
    for secret in filter(None, [userinfo, *userinfo.split(":")]):
        message = message.replace(secret, "***")
    if "resolve host" in message or "could not translate" in message:
        return (
            "the host in DATABASE_URL did not resolve. If your database password contains "
            "@ : / ? # or %, it must be percent-encoded, otherwise the host is parsed wrongly."
        )
    return message.splitlines()[0]


def _probe(url: str) -> int:
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
