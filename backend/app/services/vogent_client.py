"""Thin read-only client for the Vogent API.

Used to fetch the authoritative dial record after a call ends: duration, result
type, transcript and the version that actually ran. We poll for this rather than
trusting the webhook payload alone, because the webhook carries only a status.
"""

from __future__ import annotations

from typing import Any

import requests

from ..config import settings
from ..observability.logging import get_logger

log = get_logger(__name__)


class VogentUnavailable(Exception):
    pass


def get_dial(dial_id: str, *, timeout: float = 15.0) -> dict[str, Any]:
    config = settings()
    if not config.vogent_api_key:
        raise VogentUnavailable("VOGENT_API_KEY is not configured")
    response = requests.get(
        f"{config.vogent_api_base_url}/dials/{dial_id}",
        headers={"Authorization": f"Bearer {config.vogent_api_key}"},
        timeout=timeout,
    )
    if not response.ok:
        raise VogentUnavailable(f"dial fetch returned {response.status_code}")
    return response.json()
