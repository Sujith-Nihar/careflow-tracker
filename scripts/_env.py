"""Load .env and fetch required settings with an actionable error when one is missing."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """Load .env if it is there, otherwise trust the process environment.

    A container has no .env: its settings arrive as real environment variables,
    injected from SSM at task start. Failing here would kill the worker on boot in
    exactly the deployment this project describes. A genuinely missing setting is
    still caught by `require`, which names it.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        # A value that begins with '#' is a commented-out placeholder, not a value.
        # Mid-value '#' is left alone: passwords and URLs may contain one.
        if value.startswith("#"):
            value = ""
        os.environ.setdefault(key.strip(), value)


def require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        fail(
            f"{name} is not set. Locally, put it in .env (copy .env.example, see "
            f"docs/HUMAN_SETUP.md); in a container, inject it as an environment variable."
        )
    return value


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)
