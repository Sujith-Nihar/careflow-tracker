"""Organization resolution for the two external surfaces.

There is no user identity in this project; see docs/DECISIONS.md D10. What is
enforced is the organization boundary: a request proves which practice it belongs
to with a shared secret, and every subsequent query is scoped to that practice.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from flask import Request

from ..persistence import repositories as repo
from .errors import RequestError

FUNCTION_TOKEN_HEADER = "X-CareFlow-Token"  # noqa: S105 - a header name, not a secret
ORGANIZATION_HEADER = "X-Organization-Id"


class AuthError(RequestError):
    """The request did not prove which organization it belongs to."""


@dataclass(frozen=True, slots=True)
class Principal:
    organization_id: str
    slug: str


def from_function_token(conn: psycopg.Connection, request: Request) -> Principal:
    token = (request.headers.get(FUNCTION_TOKEN_HEADER) or "").strip()
    if not token:
        raise AuthError(401, "missing_function_token")
    org = repo.organization_by_function_token(conn, token)
    if org is None:
        raise AuthError(401, "unknown_function_token")
    return Principal(organization_id=str(org["id"]), slug=org["slug"])


def from_webhook_token(conn: psycopg.Connection, token: str) -> Principal:
    org = repo.organization_by_webhook_token(conn, (token or "").strip())
    if org is None:
        raise AuthError(401, "unknown_webhook_token")
    return Principal(organization_id=str(org["id"]), slug=org["slug"])


def from_organization_header(conn: psycopg.Connection, request: Request) -> Principal:
    organization_id = (request.headers.get(ORGANIZATION_HEADER) or "").strip()
    if not organization_id:
        raise AuthError(401, "missing_organization_header")
    try:
        org = repo.organization_by_id(conn, organization_id)
    except psycopg.errors.InvalidTextRepresentation:
        raise AuthError(401, "malformed_organization_id") from None
    if org is None:
        raise AuthError(401, "unknown_organization")
    return Principal(organization_id=str(org["id"]), slug=org["slug"])


def assert_agent_belongs(
    conn: psycopg.Connection, agent_id: str | None, principal: Principal
) -> None:
    """Reject a token and a dial that belong to different practices.

    The token alone would be enough to answer the request. This second check means
    a leaked token cannot be used to write evidence against another practice's agent.
    """
    if not agent_id:
        return
    owner = repo.organization_for_agent(conn, agent_id)
    if owner is not None and owner != principal.organization_id:
        raise AuthError(403, "agent_organization_mismatch")
