"""Call lifecycle events from Vogent.

Events may arrive late, out of order, or twice. None of that matters to the
derived status, which is a pure function of the stored rows rather than a state
machine driven by event order. Every event is stored raw and de-duplicated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from flask import Blueprint, jsonify, request

from ..domain.statement_rules import STATEMENT_RULES_VERSION, extract_statements
from ..observability.logging import bind, get_logger
from ..persistence import repositories as repo
from ..persistence.db import transaction
from ..services.status import derive_for_call
from ..services.vogent_client import get_dial
from . import auth

bp = Blueprint("vogent_webhooks", __name__, url_prefix="/vogent/webhooks")
log = get_logger(__name__)

#: Statuses that mean the call is over. Anything unrecognised is treated as still
#: running, so we never close a call on a status we do not understand.
TERMINAL_STATUSES = {"completed", "ended", "failed", "cancelled", "no_answer", "busy", "error"}


@bp.post("/<webhook_token>")
def receive(webhook_token: str) -> Any:
    body = request.get_json(silent=True) or {}
    event = str(body.get("event") or "")
    payload = body.get("payload") or {}
    dial_id = str(payload.get("dial_id") or "")

    with transaction() as conn:
        principal = auth.from_webhook_token(conn, webhook_token)
        bind(organization_id=principal.organization_id, dial_id=dial_id, event_type=event)

        fresh = repo.append_event(
            conn,
            organization_id=principal.organization_id,
            dial_id=dial_id,
            event_type=event,
            payload=body,
        )
        log.info("vogent.webhook.received", event_type=event, duplicate=not fresh)
        if not fresh:
            return jsonify({"status": "duplicate"}), 200

        call = repo.get_call_by_dial(conn, dial_id, principal.organization_id) if dial_id else None
        if call is None:
            # The call may not exist yet if no function ran. Create it so the
            # absence of any action is itself recorded and visible to staff.
            call = repo.get_or_create_call(
                conn, organization_id=principal.organization_id, dial_id=dial_id
            )
        bind(call_id=str(call["id"]))

        if event == "dial.transcript":
            _apply_transcript(conn, call, principal, payload.get("transcript") or [])
        elif event == "dial.updated":
            _apply_status(conn, call, principal, str(payload.get("status") or ""))

        derive_for_call(conn, str(call["id"]), principal.organization_id)
        return jsonify({"status": "accepted"}), 200


def _apply_transcript(
    conn: psycopg.Connection, call: dict, principal: auth.Principal, transcript: list
) -> None:
    statements = extract_statements(transcript, observed_at=datetime.now().astimezone())
    repo.replace_transcript_statements(
        conn,
        call_id=str(call["id"]),
        organization_id=principal.organization_id,
        statements=statements,
        rules_version=STATEMENT_RULES_VERSION,
    )
    repo.finalize_call(
        conn, call_id=str(call["id"]), lifecycle=call["lifecycle"], transcript=transcript
    )
    log.info("call.transcript_scored", count=len(statements), rules_version=STATEMENT_RULES_VERSION)


def _apply_status(
    conn: psycopg.Connection, call: dict, principal: auth.Principal, status: str
) -> None:
    if status.lower() not in TERMINAL_STATUSES:
        repo.finalize_call(conn, call_id=str(call["id"]), lifecycle="in_progress")
        return
    sync_dial_record(conn, call, principal)


def sync_dial_record(conn: psycopg.Connection, call: dict, principal: auth.Principal) -> str:
    """Pull the authoritative dial record and close the call.

    If Vogent cannot be reached the call is closed as `ended_unconfirmed` rather
    than left open. An unconfirmed ending still derives a status and still reaches
    staff; silently leaving it open would hide it.
    """
    try:
        dial = get_dial(call["dial_id"])
    except Exception as exc:
        log.info("call.finalized", lifecycle="ended_unconfirmed", error_type=type(exc).__name__)
        repo.finalize_call(conn, call_id=str(call["id"]), lifecycle="ended_unconfirmed")
        return "ended_unconfirmed"

    transcript = dial.get("transcript") or []
    if transcript:
        statements = extract_statements(transcript, observed_at=datetime.now().astimezone())
        repo.replace_transcript_statements(
            conn,
            call_id=str(call["id"]),
            organization_id=principal.organization_id,
            statements=statements,
            rules_version=STATEMENT_RULES_VERSION,
        )

    repo.finalize_call(
        conn,
        call_id=str(call["id"]),
        lifecycle="ended",
        started_at=_parse_time(dial.get("startedAt")),
        ended_at=_parse_time(dial.get("endedAt")),
        connected_seconds=dial.get("aiDurationSeconds") or dial.get("durationSeconds"),
        system_result_type=dial.get("systemResultType"),
        versioned_prompt_id=dial.get("versionedPromptId"),
        transcript=transcript or None,
    )
    log.info(
        "call.finalized",
        lifecycle="ended",
        connected_seconds=dial.get("aiDurationSeconds"),
        system_result_type=dial.get("systemResultType"),
    )
    return "ended"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
