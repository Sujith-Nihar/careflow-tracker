"""The pipeline every Vogent function call flows through.

The order of operations is the point. The request is persisted *before* the
simulated system is touched, and the downstream record is written *before* the
response goes back to the agent. So if anything fails midway, the evidence shows
an attempt with no result rather than a silent gap, and the call surfaces to staff.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg import errors as pg_errors

from ..domain.types import ActionOutcome
from ..observability.logging import get_logger
from ..persistence import repositories as repo
from ..simulators.base import SimulatorResult

log = get_logger(__name__)

Simulate = Callable[[dict], SimulatorResult]
PersistDownstream = Callable[[psycopg.Connection, str, SimulatorResult], str | None]


def run_action(
    conn: psycopg.Connection,
    *,
    organization_id: str,
    call: dict,
    dial_id: str,
    kind: str,
    params: dict[str, Any],
    request_id: str | None,
    simulate: Simulate,
    persist_downstream: PersistDownstream | None = None,
    transcript_snapshot: list | None = None,
) -> dict[str, Any]:
    """Execute one action idempotently and return the body to send back to Vogent."""
    key = repo.idempotency_key(dial_id, kind, params)
    existing = repo.find_execution_by_key(conn, key, organization_id)

    if existing is not None:
        return _handle_repeat(
            conn, existing=existing, organization_id=organization_id,
            call_id=str(call["id"]), kind=kind, params=params, request_id=request_id,
        )

    try:
        # A savepoint, so losing the race does not abort the surrounding transaction.
        with conn.transaction():
            execution = repo.insert_requested_execution(
                conn, call_id=str(call["id"]), organization_id=organization_id, kind=kind,
                key=key, request_payload=params, request_id=request_id,
                transcript_snapshot=transcript_snapshot,
            )
    except pg_errors.UniqueViolation:
        # Two identical requests arrived at once. The loser reads the winner's row.
        existing = repo.find_execution_by_key(conn, key, organization_id)
        if existing is None:
            raise
        return _handle_repeat(
            conn, existing=existing, organization_id=organization_id,
            call_id=str(call["id"]), kind=kind, params=params, request_id=request_id,
        )

    execution_id = str(execution["id"])
    log.info("action.requested", kind=kind, action_execution_id=execution_id)

    fault_profile = repo.get_fault_profile(conn, dial_id)
    result = simulate(fault_profile)

    for attempt in result.attempts:
        log.info(
            "action.attempt", kind=kind, action_execution_id=execution_id,
            attempt_no=attempt.attempt_no, latency_ms=attempt.latency_ms, status=attempt.result,
        )

    downstream_ref: str | None = None
    if result.succeeded and persist_downstream is not None:
        downstream_ref = persist_downstream(conn, execution_id, result)

    body = _response_body(result, downstream_ref=downstream_ref, kind=kind)
    repo.complete_execution(
        conn, execution_id=execution_id, outcome=str(result.outcome),
        response_payload=body, attempts=result.attempts_as_dicts(), downstream_ref=downstream_ref,
    )
    log.info(
        "action.completed", kind=kind, action_execution_id=execution_id,
        outcome=str(result.outcome), status=result.status,
    )
    return body


def rejected_action(
    conn: psycopg.Connection,
    *,
    organization_id: str,
    call: dict,
    dial_id: str,
    kind: str,
    params: dict[str, Any],
    request_id: str | None,
    agent_message: str,
) -> dict[str, Any]:
    """Record an attempt that never reached a simulated system because it was invalid.

    This is still evidence. The agent tried to do something and could not, which is
    materially different from the agent never trying.
    """
    key = repo.idempotency_key(dial_id, f"{kind}:rejected", params)
    existing = repo.find_execution_by_key(conn, key, organization_id)
    if existing is not None and existing["response_payload"]:
        return dict(existing["response_payload"])

    execution = repo.insert_requested_execution(
        conn, call_id=str(call["id"]), organization_id=organization_id, kind=kind,
        key=key, request_payload=params, request_id=request_id,
    )
    body = {"status": "invalid_input", "agent_message": agent_message}
    repo.complete_execution(
        conn, execution_id=str(execution["id"]), outcome=str(ActionOutcome.REJECTED),
        response_payload=body, attempts=[],
    )
    log.info(
        "action.completed", kind=kind, action_execution_id=str(execution["id"]),
        outcome=str(ActionOutcome.REJECTED), status="invalid_input",
    )
    return body


def _handle_repeat(
    conn: psycopg.Connection, *, existing: dict, organization_id: str, call_id: str,
    kind: str, params: dict, request_id: str | None,
) -> dict[str, Any]:
    """Answer a repeated request without performing the action a second time.

    A repeat is recorded as its own execution linked to the original, so the
    evidence shows that the vendor sent it twice, while exactly one downstream
    record exists. This is de-duplication, not an exactly-once guarantee: it holds
    for identical parameters on the same dial, nothing more.
    """
    original_id = str(existing["id"])

    if existing["outcome"] == str(ActionOutcome.REQUESTED):
        # The original is still running. We cannot claim a result we do not have.
        log.info("action.duplicate_in_flight", kind=kind, action_execution_id=original_id)
        return {
            "status": "unverified",
            "agent_message": "I could not confirm that just now.",
        }

    stored = dict(existing["response_payload"] or {})
    repeat = repo.insert_requested_execution(
        conn, call_id=call_id, organization_id=organization_id, kind=kind,
        key=f"{existing['idempotency_key']}:repeat:{uuid.uuid4().hex[:8]}",
        request_payload=params, request_id=request_id,
    )
    repo.complete_execution(
        conn, execution_id=str(repeat["id"]), outcome=existing["outcome"],
        response_payload=stored, attempts=[],
        downstream_ref=existing["downstream_ref"],
    )
    repo.mark_duplicate(conn, str(repeat["id"]), original_id)
    log.info(
        "action.completed", kind=kind, action_execution_id=str(repeat["id"]),
        outcome=existing["outcome"], duplicate=True,
    )
    return stored


def _response_body(result: SimulatorResult, *, downstream_ref: str | None, kind: str) -> dict:
    body: dict[str, Any] = {"status": result.status, "agent_message": result.agent_message}
    if result.failure_reason:
        body["failure_reason"] = result.failure_reason
    if downstream_ref:
        body[_REF_FIELD.get(kind, "reference_id")] = downstream_ref
    body.update(result.detail)
    return body


_REF_FIELD = {
    "schedule_appointment": "appointment_id",
    "transfer_triage": "transfer_session_id",
    "create_callback": "callback_id",
}
