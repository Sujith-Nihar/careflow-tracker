"""Export what is actually live in the workspace.

The files in `vogent/flows/` are the source we author. This writes back what
Vogent stored and is running, which is what a reviewer should judge, and what a
run's `versioned_prompt_id` points at. Function ids and header names are exported;
header values are redacted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vogent_api import REPO_ROOT, Vogent, load_ids

EXPORT_DIR = REPO_ROOT / "vogent" / "export"
REDACTED = "<redacted: set from CAREFLOW_DEMO_ORG_FUNCTION_TOKEN at sync time>"


def main() -> int:
    client = Vogent()
    ids = load_ids()
    agent_id = ids.get("agent")
    if not agent_id:
        agents = [
            a
            for a in client.list_all("/agents")
            if a["name"] == "CareFlow Demo Surgical"
        ]
        agent_id = agents[0]["id"]

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    functions = []
    for function in client.list_all("/functions"):
        detail = client.get(f"/functions/{function['id']}")
        detail["headers"] = [
            {"key": h.get("key"), "value": REDACTED}
            for h in (detail.get("headers") or [])
        ]
        functions.append(detail)
    (EXPORT_DIR / "functions.json").write_text(
        json.dumps(functions, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"  functions.json          {len(functions)} functions (header values redacted)"
    )

    prompts = client.list_all(f"/agents/{agent_id}/versioned_prompts")
    published = {"careflow-v1-baseline": "v1", "careflow-v2-evidence-aware": "v2"}
    index = {"agent_id": agent_id, "versions": {}}

    for prompt in prompts:
        short = published.get(prompt["name"])
        if short is None:
            continue
        path = EXPORT_DIR / f"{short}.json"
        path.write_text(json.dumps(prompt, indent=2, sort_keys=True) + "\n")
        definition = prompt.get("flowDefinition") or {}
        nodes = definition.get("nodes") or []
        conditioned = sum(
            1 for n in nodes for r in (n.get("transitionRules") or []) if r.get("field")
        )
        index["versions"][short] = {
            "versioned_prompt_id": prompt["id"],
            "name": prompt["name"],
            "ai_model_id": prompt.get("aiModelId"),
            "nodes": len(nodes),
            "outcome_conditioned_transitions": conditioned,
        }
        print(
            f"  {short}.json                 {prompt['id']}  {len(nodes)} nodes, {conditioned} conditioned"
        )

    (EXPORT_DIR / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n"
    )
    print(f"\nexported to {EXPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
