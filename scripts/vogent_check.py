"""Confirm VOGENT_API_KEY works, without printing anything secret.

Prints agent names and ids only; never the key, never a dial token.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

from _env import fail, load_env, require  # noqa: E402


def main() -> int:
    load_env()
    key = require("VOGENT_API_KEY")
    base = require("VOGENT_API_BASE_URL").rstrip("/")

    response = requests.get(
        f"{base}/agents",
        headers={"Authorization": f"Bearer {key}"},
        timeout=20,
    )
    if response.status_code == 401:
        fail("Vogent rejected the API key (401). Check VOGENT_API_KEY in .env.")
    if not response.ok:
        fail(f"Vogent returned {response.status_code}: {response.text[:200]}")

    body = response.json()
    agents = body.get("data", body if isinstance(body, list) else [])
    print(f"vogent reachable; {len(agents)} agent(s) in this workspace")
    for agent in agents:
        print(f"  {agent.get('id')}  {agent.get('name')}")
    if not agents:
        print("  (none yet — vogent/scripts/sync.py creates the CareFlow agent in Phase 4)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
