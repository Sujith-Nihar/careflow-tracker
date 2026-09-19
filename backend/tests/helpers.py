"""Helpers that build Vogent-shaped requests, so tests read like real traffic."""

from __future__ import annotations

import uuid
from typing import Any

from tests.conftest import DEMO_FUNCTION_TOKEN


def dial_id() -> str:
    return f"dial-{uuid.uuid4().hex[:12]}"


def envelope(dial: str, params: dict, *, agent_id: str = "agent-demo", transcript=None) -> dict:
    """The body Vogent posts to an API function."""
    return {
        "dial_id": dial,
        "dial": {
            "id": dial,
            "agent": {"id": agent_id, "name": "CareFlow"},
            "versionedPromptId": "vp-test",
            **({"transcript": transcript} if transcript else {}),
        },
        "params": params,
    }


def call_function(client, name: str, dial: str, params: dict, *, token: str = DEMO_FUNCTION_TOKEN,
                  agent_id: str = "agent-demo", transcript=None) -> Any:
    return client.post(
        f"/vogent/functions/{name}",
        json=envelope(dial, params, agent_id=agent_id, transcript=transcript),
        headers={"X-CareFlow-Token": token},
    )


def register_dial(client, org_id: str, dial: str, scenario_id: str, fault_profile: dict,
                  true_intent: str | None = None) -> Any:
    return client.post(
        "/api/eval/dials",
        json={
            "dial_id": dial, "scenario_id": scenario_id,
            "fault_profile": fault_profile, "true_intent": true_intent,
        },
        headers={"X-Organization-Id": org_id},
    )


def get_call(client, org_id: str, call_id: str) -> Any:
    return client.get(f"/api/calls/{call_id}", headers={"X-Organization-Id": org_id})


def end_call(client, dial: str, *, token: str = "test-webhook-token-demo",
             status: str = "completed") -> Any:
    """Deliver the vendor event that ends the call."""
    return client.post(
        f"/vogent/webhooks/{token}",
        json={"event": "dial.updated", "payload": {"dial_id": dial, "status": status}},
    )


def send_transcript(client, dial: str, segments: list[dict],
                    token: str = "test-webhook-token-demo") -> Any:
    return client.post(
        f"/vogent/webhooks/{token}",
        json={"event": "dial.transcript", "payload": {"dial_id": dial, "transcript": segments}},
    )


def bundle_for(client, org_id: str, dial: str) -> dict:
    """The evidence bundle for a dial, after ending the call."""
    end_call(client, dial)
    resolved = client.get(f"/api/calls/by-dial/{dial}", headers={"X-Organization-Id": org_id})
    return get_call(client, org_id, resolved.json["call_id"]).json
