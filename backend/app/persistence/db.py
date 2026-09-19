"""Connection handling.

A small pool, because every Vogent function call is on a clinical caller's clock:
a fresh TCP and TLS handshake to a hosted database would spend a meaningful slice
of the function budget doing nothing useful.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import settings

_pool: ConnectionPool | None = None


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _configure_connection(conn: psycopg.Connection) -> None:
    """Pin the schema on every pooled connection.

    This is done with a statement rather than the `options` startup parameter
    because connection poolers (Supabase runs pgbouncer) do not forward `options`,
    so the setting would be silently ignored and every query would hit `public`.
    """
    schema = settings().db_schema
    if not _IDENTIFIER.match(schema):
        raise ValueError(f"DB_SCHEMA is not a valid identifier: {schema!r}")
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema}, public")
    conn.commit()


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        config = settings()
        _pool = ConnectionPool(
            conninfo=config.database_url,
            min_size=1,
            max_size=8,
            timeout=10,
            kwargs={"row_factory": dict_row},
            configure=_configure_connection,
            open=True,
        )
    return _pool


def reset_pool() -> None:
    """Drop the pool so the next call picks up changed settings (tests use this)."""
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = None


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """One unit of work. Rolls back on any exception."""
    with pool().connection() as conn:
        with conn.transaction():
            yield conn


def query_all(conn: psycopg.Connection, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(conn: psycopg.Connection, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(conn: psycopg.Connection, sql: str, params: tuple | dict = ()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
