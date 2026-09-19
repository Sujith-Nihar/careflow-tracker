import os
import sys
from pathlib import Path

import pytest

# Tests import `app.*` directly; the backend package root is this file's parent.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

DEMO_FUNCTION_TOKEN = "test-function-token-demo"
DEMO_WEBHOOK_TOKEN = "test-webhook-token-demo"
OTHER_FUNCTION_TOKEN = "test-function-token-other"
TEST_SCHEMA = "careflow_test"


def _database_url() -> str:
    from _env import load_env

    load_env()
    return os.environ.get("DATABASE_URL", "")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _database_url()
    if not url:
        pytest.skip("DATABASE_URL is not configured")
    return url


@pytest.fixture(scope="session")
def organizations(database_url):
    """Two organizations in the test schema: one under test, one to prove isolation."""
    import psycopg

    from app.persistence.repositories import token_hash

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {TEST_SCHEMA}, public")
            cur.execute("SELECT to_regclass(%s)", (f"{TEST_SCHEMA}.organizations",))
            if cur.fetchone()[0] is None:
                pytest.skip("run `make migrate-test` first")
            ids = {}
            for slug, fn_token, wh_token in (
                ("demo-surgical", DEMO_FUNCTION_TOKEN, DEMO_WEBHOOK_TOKEN),
                ("other-practice", OTHER_FUNCTION_TOKEN, "test-webhook-token-other"),
            ):
                cur.execute(
                    """INSERT INTO organizations (slug, name, function_token_hash, webhook_token_hash)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (slug) DO UPDATE
                         SET function_token_hash = EXCLUDED.function_token_hash,
                             webhook_token_hash = EXCLUDED.webhook_token_hash
                       RETURNING id""",
                    (slug, slug, token_hash(fn_token), token_hash(wh_token)),
                )
                ids[slug] = str(cur.fetchone()[0])
        conn.commit()
    return ids


@pytest.fixture(scope="session")
def app(database_url, organizations):
    os.environ["DB_SCHEMA"] = TEST_SCHEMA
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    from app import create_app
    from app.config import settings
    from app.persistence.db import reset_pool

    settings.cache_clear()
    reset_pool()
    application = create_app()
    application.config.update(TESTING=True)
    yield application
    reset_pool()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def demo_org(organizations):
    return organizations["demo-surgical"]


@pytest.fixture
def other_org(organizations):
    return organizations["other-practice"]


@pytest.fixture(autouse=True)
def stub_dial_fetch(request, monkeypatch):
    """Return a synthetic dial record instead of calling the Vogent API.

    The finalisation path is still exercised in full; only the network hop is
    replaced, so the suite does not need workspace credentials or spend credit.
    """
    if "db" not in request.keywords:
        return

    import app.api.vogent_webhooks as webhooks

    def fake_get_dial(dial_id: str, **_kwargs):
        return {
            "id": dial_id,
            "status": "completed",
            "systemResultType": "USER_HANGUP",
            "aiDurationSeconds": 42,
            "durationSeconds": 45,
            "startedAt": "2026-09-19T17:00:00Z",
            "endedAt": "2026-09-19T17:00:45Z",
            "versionedPromptId": "vp-test",
            "transcript": getattr(request, "_fake_transcript", []),
        }

    monkeypatch.setattr(webhooks, "get_dial", fake_get_dial)
