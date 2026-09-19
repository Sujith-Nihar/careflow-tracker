"""Create or update the four CareFlow functions in the Vogent workspace.

The definitions in `vogent/functions/*.json` hold only a relative path and an
input schema. The public URL and the practice's shared secret are injected here
from the environment, so nothing secret and nothing machine-specific is committed.

Re-running this is safe: existing functions are updated in place, so the ids
already referenced by a flow version stay valid.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vogent_api import (
    REPO_ROOT,
    Vogent,
    backend_public_url,
    function_token,
    load_ids,
    save_ids,
)

FUNCTION_DIR = REPO_ROOT / "vogent" / "functions"
TOKEN_HEADER = "X-CareFlow-Token"


def build_payload(definition: dict, base_url: str, token: str) -> dict:
    payload = {
        "name": definition["name"],
        "displayName": definition.get("displayName", definition["name"]),
        "description": definition["description"],
        "type": "api",
        "apiPath": base_url + definition["path"],
        "headers": [{"key": TOKEN_HEADER, "value": token}],
        "inputJsonSchema": json.dumps(definition["inputJsonSchema"]),
    }
    if definition.get("lifecycleMessages"):
        payload["lifecycleMessages"] = definition["lifecycleMessages"]
    return payload


def main() -> int:
    client = Vogent()
    base_url = backend_public_url()
    token = function_token()

    existing = {f["name"]: f["id"] for f in client.list_all("/functions")}
    ids = load_ids()

    for path in sorted(FUNCTION_DIR.glob("*.json")):
        definition = json.loads(path.read_text())
        name = definition["name"]
        payload = build_payload(definition, base_url, token)

        if name in existing:
            # Functions are replaced with PUT; PATCH returns 405.
            client.put(f"/functions/{existing[name]}", payload)
            function_id = existing[name]
            action = "updated"
        else:
            function_id = client.post("/functions", payload)["id"]
            action = "created"

        ids[f"function.{name}"] = function_id
        print(f"  {action:8} {name:22} {function_id}")

    save_ids(ids)
    print(f"\napiPath base: {base_url}")
    print(
        f"header {TOKEN_HEADER} set from CAREFLOW_DEMO_ORG_FUNCTION_TOKEN (not printed)"
    )
    print(f"ids written to {REPO_ROOT / 'vogent' / 'ids.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
