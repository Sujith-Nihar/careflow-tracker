"""Replay a scenario through the backend without a voice call.

Replay posts Vogent-shaped function payloads straight at the API. It proves the
backend, the simulators and the derivation. It cannot prove that the live agent
chooses the right function when it hears a caller, which is why the high-risk
scenarios still get real voice runs.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import requests

from .scenarios import Scenario


@dataclass(frozen=True, slots=True)
class BackendClient:
    base_url: str
    organization_id: str
    function_token: str
    webhook_token: str
    timeout: float = 30.0

    def register_dial(
        self,
        scenario: Scenario,
        dial_id: str,
        run_id: str | None,
        agent_version: str | None = None,
    ) -> dict:
        """Bind a dial to its scenario and fault profile before any audio plays.

        `agent_version` is recorded now rather than worked out later: versioned
        prompt ids change on every republish, so a label derived afterwards would
        mislabel older calls.
        """
        return self._json(
            "POST",
            "/api/eval/dials",
            org=True,
            json={
                "agent_version": agent_version,
                "dial_id": dial_id,
                "scenario_id": scenario.id,
                "scenario_version": scenario.version,
                "evaluation_run_id": run_id,
                "true_intent": scenario.true_intent,
                "fault_profile": scenario.fault_profile,
            },
        )

    def call_function(
        self, name: str, dial_id: str, params: dict, transcript: list | None = None
    ) -> dict:
        body = {
            "dial_id": dial_id,
            "dial": {
                "id": dial_id,
                "agent": {"id": "agent-replay"},
                "versionedPromptId": "replay",
                **({"transcript": transcript} if transcript else {}),
            },
            "params": params,
        }
        response = requests.post(
            f"{self.base_url}/vogent/functions/{name}",
            json=body,
            headers={"X-CareFlow-Token": self.function_token},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def send_webhook(self, event: str, payload: dict) -> None:
        requests.post(
            f"{self.base_url}/vogent/webhooks/{self.webhook_token}",
            json={"event": event, "payload": payload},
            timeout=self.timeout,
        ).raise_for_status()

    def sync_dial(self, call_id: str) -> dict:
        """Ask the backend to fetch the dial record now rather than await a webhook."""
        return self._json("POST", f"/api/calls/{call_id}/sync-dial", org=True)

    def open_run(self, **fields) -> str:
        """Open an evaluation run and return its id."""
        body = self._json("POST", "/api/evaluation-runs", org=True, json=fields)
        return body["evaluation_run_id"]

    def record_case(self, run_id: str, **fields) -> None:
        self._json("POST", f"/api/evaluation-runs/{run_id}/cases", org=True, json=fields)

    def close_run(self, run_id: str, **fields) -> None:
        self._json("PATCH", f"/api/evaluation-runs/{run_id}", org=True, json=fields)

    def bundle_for_dial(self, dial_id: str) -> dict:
        resolved = self._json("GET", f"/api/calls/by-dial/{dial_id}", org=True)
        return self._json("GET", f"/api/calls/{resolved['call_id']}", org=True)

    def _json(self, method: str, path: str, *, org: bool = False, **kwargs) -> dict:
        headers = {"X-Organization-Id": self.organization_id} if org else {}
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()


#: What the agent would say at each step, so the transcript carries a realistic
#: promise. These are the words, not the proof; the evidence is the function result.
SPEECH = {
    "transfer_attempt": "Let me try to reach our triage nurse.",
    "transfer_failed": "The transfer did not complete.",
    "transfer_ok": "You're connected with our triage nurse now.",
    "callback_promise": "A nurse will call you back at that number.",
    "callback_failed": "I could not set up a callback either.",
    "booked": "Your appointment is booked.",
}


def replay(
    client: BackendClient, scenario: Scenario, *, run_id: str | None = None
) -> dict[str, Any]:
    """Drive one scenario and return the evidence bundle plus timing."""
    dial_id = f"replay-{scenario.id}-{uuid.uuid4().hex[:8]}"
    started = time.monotonic()
    client.register_dial(scenario, dial_id, run_id, agent_version="replay")

    transcript: list[dict] = []
    calls: list[dict] = []

    def say(text: str) -> None:
        transcript.append({"speaker": "AI", "text": text})

    if scenario.true_intent == "routine_scheduling":
        result = client.call_function(
            "schedule_appointment",
            dial_id,
            {
                "patient_ref": scenario.patient_ref,
                "preferred_date": "next Tuesday",
                "reason": "routine follow up",
            },
            transcript,
        )
        calls.append({"function": "schedule_appointment", "response": result})
        if result.get("status") == "booked":
            say(SPEECH["booked"])
        disposition = "scheduled" if result.get("status") == "booked" else "unresolved"

    else:
        say(SPEECH["transfer_attempt"])
        transfer = client.call_function(
            "transfer_triage",
            dial_id,
            {
                "patient_ref": scenario.patient_ref,
                "concern_summary": "post-operative concern",
                "callback_phone": scenario.callback_phone,
            },
            transcript,
        )
        calls.append({"function": "transfer_triage", "response": transfer})

        if transfer.get("status") == "connected":
            say(SPEECH["transfer_ok"])
            disposition = "transferred"
        else:
            say(SPEECH["transfer_failed"])
            callback = client.call_function(
                "create_callback",
                dial_id,
                {
                    "patient_ref": scenario.patient_ref,
                    "callback_phone": scenario.callback_phone,
                    "priority": "urgent",
                    "reason_code": "transfer_failed",
                },
                transcript,
            )
            calls.append({"function": "create_callback", "response": callback})

            if scenario.expected.get("callback_count") == 1:
                # Scenario E: the vendor delivers the same request twice.
                repeat = client.call_function(
                    "create_callback",
                    dial_id,
                    {
                        "patient_ref": scenario.patient_ref,
                        "callback_phone": scenario.callback_phone,
                        "priority": "urgent",
                        "reason_code": "transfer_failed",
                    },
                    transcript,
                )
                calls.append(
                    {
                        "function": "create_callback",
                        "response": repeat,
                        "duplicate": True,
                    }
                )

            if callback.get("status") == "created":
                say(SPEECH["callback_promise"])
                disposition = "callback_pending"
            else:
                say(SPEECH["callback_failed"])
                disposition = "escalation_failed"

    client.call_function(
        "report_disposition",
        dial_id,
        {
            "category": scenario.true_intent,
            "disposition": disposition,
            "summary": "replay",
        },
        transcript,
    )

    client.send_webhook(
        "dial.transcript", {"dial_id": dial_id, "transcript": transcript}
    )
    client.send_webhook("dial.updated", {"dial_id": dial_id, "status": "completed"})

    bundle = client.bundle_for_dial(dial_id)
    return {
        "dial_id": dial_id,
        "bundle": bundle,
        "function_calls": calls,
        "transcript": transcript,
        "wall_seconds": round(time.monotonic() - started, 3),
    }
