"""Errors that map to a client-visible HTTP status.

A business outcome is never one of these. A transfer that does not connect is
HTTP 200 with a `status` field, because the flow has to branch on it and tell the
caller (docs/DECISIONS.md D7). What lives here is the narrower case where the
request itself cannot be acted on: the caller is not who they claim to be, or the
body is not shaped like a request at all.
"""

from __future__ import annotations


class RequestError(Exception):
    """A rejection the client caused, carrying the status and a stable reason code."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


__all__ = ["RequestError"]
