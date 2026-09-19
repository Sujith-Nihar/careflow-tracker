"""Vogent calls the evaluation runner makes: create a browser dial, read it back."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _env import load_env, require


@dataclass(frozen=True, slots=True)
class Dial:
    dial_id: str
    session_id: str
    token: str


class VogentClient:
    def __init__(self) -> None:
        load_env()
        self.base = require("VOGENT_API_BASE_URL").rstrip("/")
        self.agent_id = require("VOGENT_AGENT_ID")
        self._key = require("VOGENT_API_KEY")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def versioned_prompt_id(self, version: str) -> str:
        return require(f"VOGENT_{version.upper()}_VERSIONED_PROMPT_ID")

    def create_browser_dial(
        self,
        *,
        versioned_prompt_id: str,
        inputs: dict[str, Any],
        webhook_url: str | None = None,
        idempotency_key: str | None = None,
        timeout_minutes: int = 3,
    ) -> Dial:
        """Create a web dial pinned to one agent version.

        `timeout_minutes` is a cost guard as much as a correctness one: a call that
        stops making progress must not sit there being billed by the second.
        """
        payload: dict[str, Any] = {
            "callAgentId": self.agent_id,
            "browserCall": True,
            "versionedModelId": versioned_prompt_id,
            "callAgentInput": inputs,
            "timeoutMinutes": timeout_minutes,
        }
        if webhook_url:
            payload["webhookUrl"] = webhook_url
        if idempotency_key:
            payload["idempotencyKey"] = idempotency_key[:255]

        response = requests.post(
            f"{self.base}/dials", headers=self._headers, json=payload, timeout=45
        )
        if not response.ok:
            raise VogentDialError(
                f"create dial -> {response.status_code}: {response.text[:400]}"
            )
        body = response.json()
        return Dial(
            dial_id=body["dialId"],
            session_id=body["sessionId"],
            token=body["dialToken"],
        )

    def get_dial(self, dial_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.base}/dials/{dial_id}", headers=self._headers, timeout=30
        )
        if not response.ok:
            raise VogentDialError(
                f"get dial -> {response.status_code}: {response.text[:300]}"
            )
        return response.json()

    def hangup(self, dial_id: str) -> None:
        requests.post(
            f"{self.base}/dials/{dial_id}/hangup", headers=self._headers, timeout=20
        )


class VogentDialError(Exception):
    pass


def webhook_url_for_backend() -> str | None:
    """Where Vogent should post call lifecycle events for this run."""
    load_env()
    base = os.environ.get("BACKEND_PUBLIC_URL", "").rstrip("/")
    token = os.environ.get("CAREFLOW_DEMO_ORG_WEBHOOK_TOKEN", "").strip()
    return f"{base}/vogent/webhooks/{token}" if base and token else None
