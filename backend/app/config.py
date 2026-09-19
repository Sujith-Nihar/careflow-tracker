"""Runtime settings, read once from the environment.

Secrets are read here and nowhere else. Nothing in this module is ever logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text().splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            # A value that begins with '#' is a commented-out placeholder, not a value.
            # Mid-value '#' is left alone: passwords and URLs may contain one.
            if value.startswith("#"):
                value = ""
            os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    db_schema: str
    vogent_api_key: str
    vogent_api_base_url: str
    log_level: str
    flask_port: int
    #: Budget for one simulator attempt, and for the whole function request.
    simulator_attempt_seconds: float
    function_budget_seconds: float
    git_sha: str

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv()
        return cls(
            database_url=os.environ.get("DATABASE_URL", ""),
            db_schema=os.environ.get("DB_SCHEMA", "public"),
            vogent_api_key=os.environ.get("VOGENT_API_KEY", ""),
            vogent_api_base_url=os.environ.get(
                "VOGENT_API_BASE_URL", "https://api.vogent.ai/api"
            ).rstrip("/"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            flask_port=int(os.environ.get("FLASK_PORT", "5000")),
            simulator_attempt_seconds=float(os.environ.get("SIMULATOR_ATTEMPT_SECONDS", "2.0")),
            function_budget_seconds=float(os.environ.get("FUNCTION_BUDGET_SECONDS", "6.0")),
            git_sha=os.environ.get("GIT_SHA", "dev"),
        )


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings.from_env()
