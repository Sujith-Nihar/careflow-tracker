"""Minimal Vogent API wrapper shared by the sync and export scripts."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _env import load_env, require


class Vogent:
    def __init__(self) -> None:
        load_env()
        self.base = require("VOGENT_API_BASE_URL").rstrip("/")
        self._key = require("VOGENT_API_KEY")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = requests.request(
            method, f"{self.base}{path}", headers=self._headers, timeout=45, **kwargs
        )
        if not response.ok:
            # Show the server's complaint, never the key.
            raise VogentError(
                f"{method} {path} -> {response.status_code}: {response.text[:500]}"
            )
        return response.json() if response.content else {}

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, payload: dict) -> Any:
        return self.request("POST", path, json=payload)

    def patch(self, path: str, payload: dict) -> Any:
        return self.request("PATCH", path, json=payload)

    def put(self, path: str, payload: dict) -> Any:
        return self.request("PUT", path, json=payload)

    def list_all(self, path: str) -> list[dict]:
        return self.get(path).get("data", [])


class VogentError(Exception):
    pass


def backend_public_url() -> str:
    url = require("BACKEND_PUBLIC_URL").rstrip("/")
    if not url.startswith("https://"):
        raise VogentError(f"BACKEND_PUBLIC_URL must be https, got {url!r}")
    return url


def function_token() -> str:
    return require("CAREFLOW_DEMO_ORG_FUNCTION_TOKEN")


def ids_path() -> Path:
    return REPO_ROOT / "vogent" / "ids.json"


def load_ids() -> dict[str, str]:
    import json

    path = ids_path()
    return json.loads(path.read_text()) if path.exists() else {}


def save_ids(ids: dict[str, str]) -> None:
    import json

    ids_path().write_text(json.dumps(ids, indent=2, sort_keys=True) + "\n")
