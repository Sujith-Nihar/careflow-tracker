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

#: The two versions the reported runs used, taken from the versioned_prompt_id
#: recorded in every artifacts/**/metrics.json. Publishing keeps the same name, so
#: a name match alone returns whichever of the 60-odd versions the API happens to
#: list last. Pinning the ids is what makes this directory "what actually ran".
REPORTED_RUNS = {
    "v1": "d37760bc-a8a3-4e7f-80d1-247264cd4a94",
    "v2": "dfc9502a-073c-42f0-b8f2-77afe4a35123",
}


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
    by_id = {prompt_id: short for short, prompt_id in REPORTED_RUNS.items()}
    index = {"agent_id": agent_id, "versions": {}}

    for prompt in prompts:
        short = by_id.get(prompt["id"])
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

    missing = sorted(set(REPORTED_RUNS) - set(index["versions"]))
    if missing:
        print(
            f"\nfailed: no versioned prompt in the workspace for {', '.join(missing)}"
        )
        return 1

    (EXPORT_DIR / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n"
    )
    print(f"\nexported to {EXPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
