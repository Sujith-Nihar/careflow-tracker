"""Create the CareFlow agent and both flow versions in the Vogent workspace.

The flow files in `vogent/flows/` are the source of truth. They refer to functions
by name (`__transfer_triage__`) rather than by workspace id, so the same files can
be applied to a fresh workspace and still produce the same agent.

V1 and V2 are two versioned prompts on one agent, pinned per dial at run time. That
keeps the functions, the model and the policy identical between them, so the only
variable in the comparison is how the flow reacts to a function result.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vogent_api import REPO_ROOT, Vogent, VogentError, load_ids, save_ids  # noqa: E402

FLOW_DIR = REPO_ROOT / "vogent" / "flows"
AGENT_NAME = "CareFlow Demo Surgical"

#: Both versions run the same model so the flow is the only variable. A flow-tuned
#: model is used because these agents are graphs, not free-form prompts.
MODEL_NAME = "GPT-5.4 Flow"
VOICE_NAME = "Emily"

PLACEHOLDER = re.compile(r"^__([a-z_]+)__$")
OUTPUT_PLACEHOLDER = re.compile(r"^__outputs\.([a-z_]+)__$")


def resolve_flow(flow: dict, shared: dict, function_ids: dict[str, str]) -> dict:
    """Replace name placeholders with workspace ids and expand shared output schemas."""
    nodes = []
    for node in flow["nodes"]:
        data = json.loads(json.dumps(node["nodeData"]))  # deep copy
        if node["type"] == "function":
            match = PLACEHOLDER.match(str(data.get("functionId", "")))
            if not match:
                raise VogentError(f"node {node['id']} has an unresolved functionId")
            name = match.group(1)
            if name not in function_ids:
                raise VogentError(f"function {name!r} is not in the workspace; run sync_functions.py")
            data["functionId"] = function_ids[name]

            out_match = OUTPUT_PLACEHOLDER.match(str(data.get("outputs", "")))
            if out_match:
                data["outputs"] = shared["function_outputs"][out_match.group(1)]

        nodes.append(
            {
                "id": node["id"],
                "name": node["name"],
                "type": node["type"],
                "nodeData": data,
                "transitionRules": node["transitionRules"],
            }
        )

    return {
        "nodes": nodes,
        "globalContext": shared["globalContext"],
        "openingLineType": shared["openingLineType"],
        # Without this the agent waits for the caller to speak first. On a browser
        # call that is silence on both sides until a timeout, which is exactly how
        # the first voice run burned 150 seconds (see docs/INVESTIGATIONS.md INV-1).
        "aiOpen": bool(shared.get("aiOpen", True)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", default="v1,v2", help="which flow files to publish")
    args = parser.parse_args()

    client = Vogent()
    ids = load_ids()
    shared = json.loads((FLOW_DIR / "_shared.json").read_text())

    function_ids = {f["name"]: f["id"] for f in client.list_all("/functions")}
    if not function_ids:
        raise VogentError("no functions in the workspace; run sync_functions.py first")

    model_id = _lookup(client, "/models", MODEL_NAME, "model")
    voice_id = _lookup(client, "/voices", VOICE_NAME, "voice", key="voices")

    agent_id = _ensure_agent(client, ids, model_id, voice_id)

    for version in args.versions.split(","):
        version = version.strip()
        flow = json.loads((FLOW_DIR / f"{version}.json").read_text())
        definition = resolve_flow(flow, shared, function_ids)
        payload = {
            "aiModelId": model_id,
            "agentType": "CUSTOM_FLOW",
            "name": flow["version_name"],
            "flowDefinition": definition,
            # No modelOptionValues. A temperature of 0.2 is accepted at publish time
            # and then produces an agent that never speaks; the model's own default
            # is the only setting that works. See INVESTIGATIONS.md INV-3.
        }
        created = client.post(f"/agents/{agent_id}/versioned_prompts", payload)
        ids[f"versioned_prompt.{version}"] = created["id"]
        conditioned = sum(
            1 for n in definition["nodes"] for r in n["transitionRules"] if r.get("field")
        )
        print(
            f"  published {version}  {created['id']}  "
            f"{len(definition['nodes'])} nodes, {conditioned} outcome-conditioned transitions"
        )

    save_ids(ids)
    print("\nAdd these to .env:")
    print(f"  VOGENT_AGENT_ID={agent_id}")
    for version in args.versions.split(","):
        key = f"versioned_prompt.{version.strip()}"
        print(f"  VOGENT_{version.strip().upper()}_VERSIONED_PROMPT_ID={ids[key]}")
    return 0


def _lookup(client: Vogent, path: str, name: str, label: str, key: str = "data") -> str:
    items = client.get(path).get(key, [])
    for item in items:
        if item.get("name") == name:
            return item["id"]
    available = ", ".join(sorted(i.get("name", "?") for i in items)[:8])
    raise VogentError(f"{label} {name!r} not found. Available: {available}")


def _ensure_agent(client: Vogent, ids: dict, model_id: str, voice_id: str) -> str:
    for agent in client.list_all("/agents"):
        if agent["name"] == AGENT_NAME:
            ids["agent"] = agent["id"]
            print(f"  reusing agent {agent['id']}")
            return agent["id"]

    created = client.post(
        "/agents",
        {
            "name": AGENT_NAME,
            "language": "en",
            "defaultVoiceId": voice_id,
            "inboundWebhookUrl": "",
            "inboundWebhookResponse": False,
            "defaultVersionedPrompt": {
                "aiModelId": model_id,
                "agentType": "CUSTOM_FLOW",
                "name": "careflow-bootstrap",
            },
        },
    )
    ids["agent"] = created["id"]
    print(f"  created agent {created['id']}")
    return created["id"]


if __name__ == "__main__":
    raise SystemExit(main())
