"""Apply backend/migrations/*.sql in order, once each.

Applied migrations are recorded in schema_migrations, so running this twice is a
no-op. With --test-schema the whole schema is created inside careflow_test, which
is what the integration tests use.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg
from _env import ROOT, load_env, require

MIGRATIONS = ROOT / "backend" / "migrations"
TEST_SCHEMA = "careflow_test"

TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    text PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test-schema", action="store_true", help=f"apply into {TEST_SCHEMA}"
    )
    args = parser.parse_args()

    load_env()
    url = require("DATABASE_URL")

    with psycopg.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            if args.test_schema:
                cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
                cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
                cur.execute(f"SET search_path TO {TEST_SCHEMA}, public")
                print(f"recreated schema {TEST_SCHEMA}")
            cur.execute(TRACKING_TABLE)
        conn.commit()

        applied = 0
        for path in sorted(MIGRATIONS.glob("*.sql")):
            sql = path.read_text()
            checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]
            with conn.cursor() as cur:
                if args.test_schema:
                    cur.execute(f"SET search_path TO {TEST_SCHEMA}, public")
                cur.execute(
                    "SELECT checksum FROM schema_migrations WHERE filename = %s",
                    (path.name,),
                )
                row = cur.fetchone()
                if row:
                    if row[0] != checksum:
                        print(
                            f"warning: {path.name} changed since it was applied ({row[0]} -> {checksum})"
                        )
                    print(f"  skip {path.name} (already applied)")
                    continue
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )
                applied += 1
                print(f"  applied {path.name}")
            conn.commit()

    print(f"{applied} migration(s) applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
