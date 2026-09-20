"""The four functions the voice agent can invoke.

Every business outcome is returned as HTTP 200 with a `status` field. A failed
transfer is not a server error: it is a fact the flow must be able to branch on
and tell the caller about. Only authentication and malformed envelopes get 4xx.
"""

from __future__ import annotations

from typing import Any

import psycopg
from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from ..observability.logging import bind, get_logger
from ..persistence import repositories as repo
from ..persistence.db import transaction
from ..services import parsing
from ..services.actions import rejected_action, run_action
from ..simulators import callback_queue, scheduler, triage_line
from ..simulators.base import Clock, SimulatorResult
from . import auth
from .errors import RequestError
from .schemas import (
    CreateCallbackParams,
    FunctionEnvelope,
    ReportDispositionParams,
    ScheduleAppointmentParams,
    TransferTriageParams,
)

bp = Blueprint("vogent_functions", __name__, url_prefix="/vogent/functions")
log = get_logger(__name__)


def _open_call(
    conn: psycopg.Connection, envelope: FunctionEnvelope, principal: auth.Principal
) -> dict:
    auth.assert_agent_belongs(conn, envelope.vogent_agent_id, principal)
    call = repo.get_or_create_call(
        conn,
        organization_id=principal.organization_id,
        dial_id=envelope.dial_id,
        vogent_agent_id=envelope.vogent_agent_id,
        versioned_prompt_id=envelope.versioned_prompt_id,
    )
    bind(call_id=str(call["id"]), dial_id=envelope.dial_id, scenario_id=call.get("scenario_id"))
    return call


def _envelope() -> FunctionEnvelope:
    """Parse the outer envelope, or reject the request.

    Params are parsed leniently further in, because a speech model producing an odd
    value is expected and recoverable. The envelope is different: with no dial_id
    there is no call to attach anything to, so there is nothing to recover.
    """
    try:
        return FunctionEnvelope.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        raise RequestError(400, "malformed_envelope") from None


def _finish(conn: psycopg.Connection, call: dict, principal: auth.Principal, body: dict) -> Any:
    """Answer the agent immediately.

    Status is deliberately not derived here. The caller is on the phone, the
    response body does not carry a status, and derivation is a pure function of
    rows that are already committed, so it costs nothing to compute on read.
    """
    return jsonify(body), 200


@bp.post("/schedule_appointment")
def schedule_appointment() -> Any:
    envelope = _envelope()
    with transaction() as conn:
        principal = auth.from_function_token(conn, request)
        bind(organization_id=principal.organization_id, function="schedule_appointment")
        log.info("vogent.function.received", function="schedule_appointment")
        call = _open_call(conn, envelope, principal)

        try:
            params = ScheduleAppointmentParams.model_validate(envelope.params)
        except ValidationError:
            return _finish(
                conn,
                call,
                principal,
                rejected_action(
                    conn,
                    organization_id=principal.organization_id,
                    call=call,
                    dial_id=envelope.dial_id,
                    kind="schedule_appointment",
                    params=envelope.params,
                    request_id=g.get("request_id"),
                    agent_message="I could not read those appointment details.",
                ),
            )

        patient_ref = envelope.resolved("patient_ref", params.patient_ref)
        slot = parsing.parse_preferred_date(params.preferred_date)
        if slot is None:
            return _finish(
                conn,
                call,
                principal,
                rejected_action(
                    conn,
                    organization_id=principal.organization_id,
                    call=call,
                    dial_id=envelope.dial_id,
                    kind="schedule_appointment",
                    params=params.model_dump(),
                    request_id=g.get("request_id"),
                    agent_message="I could not work out which day you meant.",
                ),
            )

        def simulate(profile: dict) -> SimulatorResult:
            return scheduler.book_appointment(
                slot=slot, fault=profile.get("scheduler", scheduler.BOOK), clock=Clock()
            )

        def persist(conn: psycopg.Connection, execution_id: str, result: SimulatorResult) -> str:
            row = repo.insert_appointment(
                conn,
                organization_id=principal.organization_id,
                execution_id=execution_id,
                patient_ref=patient_ref or "unknown",
                slot=slot,
            )
            return str(row["id"])

        body = run_action(
            conn,
            organization_id=principal.organization_id,
            call=call,
            dial_id=envelope.dial_id,
            kind="schedule_appointment",
            params=params.model_dump() | {"patient_ref": patient_ref},
            request_id=g.get("request_id"),
            simulate=simulate,
            persist_downstream=persist,
            transcript_snapshot=envelope.transcript_snapshot,
        )
        return _finish(conn, call, principal, body)


@bp.post("/transfer_triage")
def transfer_triage() -> Any:
    envelope = _envelope()
    with transaction() as conn:
        principal = auth.from_function_token(conn, request)
        bind(organization_id=principal.organization_id, function="transfer_triage")
        log.info("vogent.function.received", function="transfer_triage")
        call = _open_call(conn, envelope, principal)

        try:
            params = TransferTriageParams.model_validate(envelope.params)
        except ValidationError:
            return _finish(
                conn,
                call,
                principal,
                rejected_action(
                    conn,
                    organization_id=principal.organization_id,
                    call=call,
                    dial_id=envelope.dial_id,
                    kind="transfer_triage",
                    params=envelope.params,
                    request_id=g.get("request_id"),
                    agent_message="I could not read those details.",
                ),
            )

        patient_ref = envelope.resolved("patient_ref", params.patient_ref)

        def simulate(profile: dict) -> SimulatorResult:
            return triage_line.connect_to_triage(
                fault=profile.get("transfer", triage_line.CONNECT), clock=Clock()
            )

        def persist(conn: psycopg.Connection, execution_id: str, result: SimulatorResult) -> str:
            row = repo.insert_transfer_session(
                conn,
                organization_id=principal.organization_id,
                execution_id=execution_id,
                status="connected",
                failure_reason=None,
            )
            return str(row["id"])

        stored = params.model_dump() | {"patient_ref": patient_ref}
        body = run_action(
            conn,
            organization_id=principal.organization_id,
            call=call,
            dial_id=envelope.dial_id,
            kind="transfer_triage",
            params=stored,
            request_id=g.get("request_id"),
            simulate=simulate,
            persist_downstream=persist,
            transcript_snapshot=envelope.transcript_snapshot,
        )

        # A transfer that did not connect still leaves a call-detail record. The
        # attempt is evidence, and staff need to see that the line was tried.
        if body.get("status") in {"failed", "unverified"}:
            _record_failed_transfer(conn, principal, call, envelope, stored, body)

        return _finish(conn, call, principal, body)


def _record_failed_transfer(
    conn: psycopg.Connection,
    principal: auth.Principal,
    call: dict,
    envelope: FunctionEnvelope,
    params: dict,
    body: dict,
) -> None:
    """Persist the call-detail record for a transfer that did not connect.

    The params must be the same normalised dict `run_action` was given, or the
    idempotency key will not match the execution it belongs to.
    """
    key = repo.idempotency_key(envelope.dial_id, "transfer_triage", params)
    execution = repo.find_execution_by_key(conn, key, principal.organization_id)
    if execution is None:
        return
    existing = repo.load_evidence(conn, str(call["id"]), principal.organization_id)
    if existing and any(
        t.action_execution_id == str(execution["id"]) for t in existing.transfer_sessions
    ):
        return
    repo.insert_transfer_session(
        conn,
        organization_id=principal.organization_id,
        execution_id=str(execution["id"]),
        status=body["status"],
        failure_reason=body.get("failure_reason"),
    )


@bp.post("/create_callback")
def create_callback() -> Any:
    envelope = _envelope()
    with transaction() as conn:
        principal = auth.from_function_token(conn, request)
        bind(organization_id=principal.organization_id, function="create_callback")
        log.info("vogent.function.received", function="create_callback")
        call = _open_call(conn, envelope, principal)

        try:
            params = CreateCallbackParams.model_validate(envelope.params)
        except ValidationError:
            return _finish(
                conn,
                call,
                principal,
                rejected_action(
                    conn,
                    organization_id=principal.organization_id,
                    call=call,
                    dial_id=envelope.dial_id,
                    kind="create_callback",
                    params=envelope.params,
                    request_id=g.get("request_id"),
                    agent_message="I could not read those callback details.",
                ),
            )

        patient_ref = envelope.resolved("patient_ref", params.patient_ref)
        phone = parsing.normalize_phone(envelope.resolved("callback_phone", params.callback_phone))
        if phone is None:
            return _finish(
                conn,
                call,
                principal,
                rejected_action(
                    conn,
                    organization_id=principal.organization_id,
                    call=call,
                    dial_id=envelope.dial_id,
                    kind="create_callback",
                    params=params.model_dump(),
                    request_id=g.get("request_id"),
                    agent_message="I could not read that phone number back correctly.",
                ),
            )

        # The flow asks for a callback after every transfer attempt, because Vogent
        # function nodes cannot branch on a function result. The decision therefore
        # belongs here, where the authoritative transfer state already exists.
        evidence = repo.load_evidence(conn, str(call["id"]), principal.organization_id)
        already_connected = evidence is not None and any(
            t.status == "connected" for t in evidence.transfer_sessions
        )
        if already_connected and params.reason_code == "transfer_failed":
            body = {
                "status": "not_needed",
                "agent_message": "No callback is needed; the caller reached the triage nurse.",
            }
            _record_not_applicable(
                conn,
                principal,
                call,
                envelope,
                params.model_dump() | {"callback_phone": phone},
                body,
            )
            return _finish(conn, call, principal, body)

        def simulate(profile: dict) -> SimulatorResult:
            return callback_queue.create_callback(
                priority=params.priority,
                fault=profile.get("callback", callback_queue.CREATE),
                clock=Clock(),
            )

        def persist(conn: psycopg.Connection, execution_id: str, result: SimulatorResult) -> str:
            row = repo.insert_callback_request(
                conn,
                organization_id=principal.organization_id,
                execution_id=execution_id,
                patient_ref=patient_ref or "unknown",
                priority=params.priority,
                reason_code=params.reason_code,
            )
            return str(row["id"])

        stored = params.model_dump() | {"callback_phone": phone, "patient_ref": patient_ref}
        body = run_action(
            conn,
            organization_id=principal.organization_id,
            call=call,
            dial_id=envelope.dial_id,
            kind="create_callback",
            params=stored,
            request_id=g.get("request_id"),
            simulate=simulate,
            persist_downstream=persist,
            transcript_snapshot=envelope.transcript_snapshot,
        )
        body["priority"] = params.priority
        return _finish(conn, call, principal, body)


def _record_not_applicable(
    conn: psycopg.Connection,
    principal: auth.Principal,
    call: dict,
    envelope: FunctionEnvelope,
    params: dict,
    body: dict,
) -> None:
    """Record that a fallback was asked for and correctly not taken.

    This is evidence too. Without it the call would look as though the flow never
    considered a fallback, which is exactly the ambiguity this project exists to remove.
    """
    key = repo.idempotency_key(envelope.dial_id, "create_callback:not_applicable", params)
    if repo.find_execution_by_key(conn, key, principal.organization_id) is not None:
        return
    execution = repo.insert_requested_execution(
        conn,
        call_id=str(call["id"]),
        organization_id=principal.organization_id,
        kind="create_callback",
        key=key,
        request_payload=params,
        request_id=g.get("request_id"),
    )
    repo.complete_execution(
        conn,
        execution_id=str(execution["id"]),
        outcome="not_applicable",
        response_payload=body,
        attempts=[],
    )
    log.info(
        "action.completed",
        kind="create_callback",
        action_execution_id=str(execution["id"]),
        outcome="not_applicable",
        status="not_needed",
    )


@bp.post("/report_disposition")
def report_disposition() -> Any:
    """Record what the agent believes happened.

    This is a claim, and it is stored as one. It never contributes to completion.
    Contrasting it with the derived status is what surfaces the reported failure.
    """
    envelope = _envelope()
    with transaction() as conn:
        principal = auth.from_function_token(conn, request)
        bind(organization_id=principal.organization_id, function="report_disposition")
        log.info("vogent.function.received", function="report_disposition")
        call = _open_call(conn, envelope, principal)
        try:
            params = ReportDispositionParams.model_validate(envelope.params or {})
        except ValidationError:
            # Unreadable, but the agent still tried to file an account of the call.
            # Record the attempt rather than losing it behind a 500.
            return _finish(
                conn,
                call,
                principal,
                rejected_action(
                    conn,
                    organization_id=principal.organization_id,
                    call=call,
                    dial_id=envelope.dial_id,
                    kind="report_disposition",
                    params=envelope.params,
                    request_id=g.get("request_id"),
                    agent_message="",
                ),
            )

        def simulate(_profile: dict) -> SimulatorResult:
            from ..domain.types import ActionOutcome

            return SimulatorResult(
                outcome=ActionOutcome.SUCCEEDED,
                status="recorded",
                agent_message="",
            )

        def persist(conn: psycopg.Connection, execution_id: str, _result: SimulatorResult) -> None:
            repo.set_agent_classified_intent(conn, str(call["id"]), params.category)
            repo.insert_statement(
                conn,
                call_id=str(call["id"]),
                organization_id=principal.organization_id,
                kind="reported_disposition",
                source="function_param",
                sequence_no=_next_sequence(conn, str(call["id"]), principal.organization_id),
                disposition=params.disposition,
                evidence_text=params.summary or None,
            )

        body = run_action(
            conn,
            organization_id=principal.organization_id,
            call=call,
            dial_id=envelope.dial_id,
            kind="report_disposition",
            params=params.model_dump(),
            request_id=g.get("request_id"),
            simulate=simulate,
            persist_downstream=persist,
        )
        return _finish(conn, call, principal, body)


def _next_sequence(conn: psycopg.Connection, call_id: str, organization_id: str) -> int:
    evidence = repo.load_evidence(conn, call_id, organization_id)
    if evidence is None or not evidence.agent_statements:
        return 1000  # disposition reports sort after transcript statements
    return max(s.sequence_no for s in evidence.agent_statements) + 1
