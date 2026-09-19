"""Create the synthetic organizations this project runs against.

Two organizations exist on purpose. The second one never receives traffic; it is
there so the isolation tests can prove that one practice cannot read another's
calls. Tokens are stored as hashes, so a database dump does not hand over access.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import psycopg  # noqa: E402

from _env import fail, load_env, require  # noqa: E402
from app.persistence.repositories import token_hash  # noqa: E402

DEMO_SLUG = "demo-surgical"
OTHER_SLUG = "other-practice"


def upsert(conn: psycopg.Connection, slug: str, name: str, fn_token: str, wh_token: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO organizations (slug, name, function_token_hash, webhook_token_hash)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (slug) DO UPDATE
                   SET name = EXCLUDED.name,
                       function_token_hash = EXCLUDED.function_token_hash,
                       webhook_token_hash = EXCLUDED.webhook_token_hash
               RETURNING id""",
            (slug, name, token_hash(fn_token), token_hash(wh_token)),
        )
        return str(cur.fetchone()[0])


def main() -> int:
    load_env()
    url = require("DATABASE_URL")
    fn_token = require("CAREFLOW_DEMO_ORG_FUNCTION_TOKEN")
    wh_token = require("CAREFLOW_DEMO_ORG_WEBHOOK_TOKEN")
    if fn_token == wh_token:
        fail("the function token and the webhook token must be different values")

    with psycopg.connect(url, connect_timeout=15) as conn:
        demo_id = upsert(conn, DEMO_SLUG, "Demo Surgical Associates", fn_token, wh_token)
        other_id = upsert(
            conn, OTHER_SLUG, "Other Practice (isolation tests only)",
            f"other-{fn_token}", f"other-{wh_token}",
        )
        conn.commit()

    print(f"organization {DEMO_SLUG:16} {demo_id}")
    print(f"organization {OTHER_SLUG:16} {other_id}")
    print()
    print("Add this line to .env so the dashboard and eval runner know which practice to use:")
    print(f"  DEMO_ORGANIZATION_ID={demo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
