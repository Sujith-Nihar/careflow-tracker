"""Every database query in the application.

Two rules hold throughout:
  * every read and write is scoped by organization_id;
  * evidence rows are written once and completed once, never rewritten.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import psycopg

from ..domain.types import (
    ActionExecution,
    ActionKind,
    ActionOutcome,
    AgentStatement,
    Appointment,
    AppointmentStatus,
    CallbackPriority,
    CallbackRequest,
    CallbackStatus,
    CallEvidence,
    CallRecord,
    Disposition,
    Intent,
    Lifecycle,
    StaffAction,
    StaffActionKind,
    StatementKind,
    StatementSource,
    TransferSession,
    TransferStatus,
)
from .db import execute, query_all, query_one


def token_hash(token: str) -> str:
    """Tokens are compared by hash so a database dump does not hand over access."""
    return hashlib.sha256(token.encode()).hexdigest()


def idempotency_key(dial_id: str, function: str, params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{dial_id}|{function}|{canonical}".encode()).hexdigest()


# ---------------------------------------------------------------- organizations
def organization_by_function_token(conn: psycopg.Connection, token: str) -> dict | None:
    return query_one(
        conn,
        "SELECT id, slug, name FROM organizations WHERE function_token_hash = %s",
        (token_hash(token),),
    )


def organization_by_webhook_token(conn: psycopg.Connection, token: str) -> dict | None:
    return query_one(
        conn,
        "SELECT id, slug, name FROM organizations WHERE webhook_token_hash = %s",
        (token_hash(token),),
    )


def organization_by_id(conn: psycopg.Connection, organization_id: str) -> dict | None:
    return query_one(conn, "SELECT id, slug, name FROM organizations WHERE id = %s", (organization_id,))


def organization_for_agent(conn: psycopg.Connection, vogent_agent_id: str) -> str | None:
    row = query_one(
        conn,
        "SELECT organization_id FROM agent_registrations WHERE vogent_agent_id = %s",
        (vogent_agent_id,),
    )
    return str(row["organization_id"]) if row else None


def register_agent(conn: psycopg.Connection, vogent_agent_id: str, organization_id: str) -> None:
    execute(
        conn,
        """INSERT INTO agent_registrations (vogent_agent_id, organization_id)
           VALUES (%s, %s)
           ON CONFLICT (vogent_agent_id) DO UPDATE SET organization_id = EXCLUDED.organization_id""",
        (vogent_agent_id, organization_id),
    )


# ------------------------------------------------------------------------ calls
def get_or_create_call(
    conn: psycopg.Connection,
    *,
    organization_id: str,
    dial_id: str,
    vogent_agent_id: str | None = None,
    versioned_prompt_id: str | None = None,
) -> dict:
    """Find the call for this dial, creating it if the function call arrived first.

    A fault profile registered before the dial supplies the scenario identifiers,
    so evaluation calls are labelled without trusting the model to relay them.
    """
    row = query_one(
        conn,
        "SELECT * FROM calls WHERE organization_id = %s AND dial_id = %s",
        (organization_id, dial_id),
    )
    if row:
        if vogent_agent_id or versioned_prompt_id:
            execute(
                conn,
                """UPDATE calls
                      SET vogent_agent_id = COALESCE(%s, vogent_agent_id),
                          versioned_prompt_id = COALESCE(%s, versioned_prompt_id),
                          lifecycle = CASE WHEN lifecycle = 'registered' THEN 'in_progress'
                                           ELSE lifecycle END,
                          updated_at = now()
                    WHERE id = %s""",
                (vogent_agent_id, versioned_prompt_id, row["id"]),
            )
            row = query_one(conn, "SELECT * FROM calls WHERE id = %s", (row["id"],))
        return row

    profile = query_one(
        conn,
        "SELECT scenario_id, evaluation_run_id, true_intent FROM fault_profiles WHERE dial_id = %s",
        (dial_id,),
    ) or {}

    return query_one(
        conn,
        """INSERT INTO calls (organization_id, dial_id, vogent_agent_id, versioned_prompt_id,
                              scenario_id, evaluation_run_id, true_intent, lifecycle)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'in_progress')
           RETURNING *""",
        (
            organization_id, dial_id, vogent_agent_id, versioned_prompt_id,
            profile.get("scenario_id"), profile.get("evaluation_run_id"), profile.get("true_intent"),
        ),
    )


def get_call(conn: psycopg.Connection, call_id: str, organization_id: str) -> dict | None:
    return query_one(
        conn, "SELECT * FROM calls WHERE id = %s AND organization_id = %s", (call_id, organization_id)
    )


def get_call_by_dial(conn: psycopg.Connection, dial_id: str, organization_id: str) -> dict | None:
    return query_one(
        conn,
        "SELECT * FROM calls WHERE dial_id = %s AND organization_id = %s",
        (dial_id, organization_id),
    )


def set_agent_classified_intent(conn: psycopg.Connection, call_id: str, intent: str) -> None:
    execute(
        conn,
        "UPDATE calls SET agent_classified_intent = %s, updated_at = now() WHERE id = %s",
        (intent, call_id),
    )


def finalize_call(
    conn: psycopg.Connection,
    *,
    call_id: str,
    lifecycle: str,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    connected_seconds: int | None = None,
    system_result_type: str | None = None,
    versioned_prompt_id: str | None = None,
    transcript: list | None = None,
) -> None:
    execute(
        conn,
        """UPDATE calls
              SET lifecycle = %s,
                  started_at = COALESCE(%s, started_at),
                  ended_at = COALESCE(%s, ended_at),
                  connected_seconds = COALESCE(%s, connected_seconds),
                  system_result_type = COALESCE(%s, system_result_type),
                  versioned_prompt_id = COALESCE(%s, versioned_prompt_id),
                  transcript = COALESCE(%s, transcript),
                  updated_at = now()
            WHERE id = %s""",
        (
            lifecycle, started_at, ended_at, connected_seconds, system_result_type,
            versioned_prompt_id, json.dumps(transcript) if transcript is not None else None, call_id,
        ),
    )


def calls_for_attention(
    conn: psycopg.Connection, organization_id: str, *, limit: int = 100
) -> list[dict]:
    """Ended calls, newest first. Severity ordering is applied after derivation."""
    return query_all(
        conn,
        """SELECT * FROM calls
            WHERE organization_id = %s
            ORDER BY COALESCE(ended_at, created_at) DESC
            LIMIT %s""",
        (organization_id, limit),
    )


# ------------------------------------------------------------- action executions
def find_execution_by_key(conn: psycopg.Connection, key: str, organization_id: str) -> dict | None:
    return query_one(
        conn,
        "SELECT * FROM action_executions WHERE idempotency_key = %s AND organization_id = %s",
        (key, organization_id),
    )


def insert_requested_execution(
    conn: psycopg.Connection,
    *,
    call_id: str,
    organization_id: str,
    kind: str,
    key: str,
    request_payload: dict,
    request_id: str | None,
    transcript_snapshot: list | None = None,
) -> dict:
    return query_one(
        conn,
        """INSERT INTO action_executions
               (call_id, organization_id, kind, idempotency_key, request_payload,
                transcript_snapshot, request_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            call_id, organization_id, kind, key, json.dumps(request_payload),
            json.dumps(transcript_snapshot) if transcript_snapshot else None, request_id,
        ),
    )


def complete_execution(
    conn: psycopg.Connection,
    *,
    execution_id: str,
    outcome: str,
    response_payload: dict,
    attempts: list[dict],
    downstream_ref: str | None = None,
) -> None:
    execute(
        conn,
        """UPDATE action_executions
              SET outcome = %s, response_payload = %s, attempts = %s,
                  downstream_ref = %s, completed_at = now()
            WHERE id = %s""",
        (outcome, json.dumps(response_payload), json.dumps(attempts), downstream_ref, execution_id),
    )


def mark_duplicate(conn: psycopg.Connection, execution_id: str, original_id: str) -> None:
    execute(
        conn, "UPDATE action_executions SET duplicate_of_id = %s WHERE id = %s",
        (original_id, execution_id),
    )


# ------------------------------------------------- simulated downstream systems
def insert_appointment(
    conn: psycopg.Connection, *, organization_id: str, execution_id: str,
    patient_ref: str, slot: datetime,
) -> dict:
    return query_one(
        conn,
        """INSERT INTO appointments (organization_id, action_execution_id, patient_ref, slot)
           VALUES (%s, %s, %s, %s) RETURNING *""",
        (organization_id, execution_id, patient_ref, slot),
    )


def insert_transfer_session(
    conn: psycopg.Connection, *, organization_id: str, execution_id: str,
    status: str, failure_reason: str | None, attempt_no: int = 1,
) -> dict:
    return query_one(
        conn,
        """INSERT INTO transfer_sessions
               (organization_id, action_execution_id, status, failure_reason, attempt_no)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (organization_id, execution_id, status, failure_reason, attempt_no),
    )


def insert_callback_request(
    conn: psycopg.Connection, *, organization_id: str, execution_id: str,
    patient_ref: str, priority: str, reason_code: str,
) -> dict:
    return query_one(
        conn,
        """INSERT INTO callback_requests
               (organization_id, action_execution_id, patient_ref, priority, reason_code)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (organization_id, execution_id, patient_ref, priority, reason_code),
    )


def complete_callback(
    conn: psycopg.Connection, *, callback_id: str, organization_id: str, actor: str
) -> dict | None:
    return query_one(
        conn,
        """UPDATE callback_requests
              SET status = 'completed', completed_by = %s, completed_at = now()
            WHERE id = %s AND organization_id = %s AND status = 'created'
        RETURNING *""",
        (actor, callback_id, organization_id),
    )


# ------------------------------------------------------------- agent statements
def insert_statement(
    conn: psycopg.Connection, *, call_id: str, organization_id: str, kind: str, source: str,
    sequence_no: int, disposition: str | None = None, evidence_text: str | None = None,
    rules_version: int | None = None,
) -> None:
    execute(
        conn,
        """INSERT INTO agent_statements
               (call_id, organization_id, kind, source, sequence_no, disposition,
                evidence_text, rules_version)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (call_id, organization_id, kind, source, sequence_no, disposition,
         evidence_text, rules_version),
    )


def replace_transcript_statements(
    conn: psycopg.Connection, *, call_id: str, organization_id: str,
    statements: list[AgentStatement], rules_version: int,
) -> None:
    """Re-scoring a transcript replaces only the rule-derived statements.

    Statements captured from function parameters are first-hand records of a
    request the agent made and are never recomputed.
    """
    execute(
        conn,
        "DELETE FROM agent_statements WHERE call_id = %s AND source = 'transcript_rule'",
        (call_id,),
    )
    for statement in statements:
        insert_statement(
            conn, call_id=call_id, organization_id=organization_id, kind=str(statement.kind),
            source=str(statement.source), sequence_no=statement.sequence_no,
            evidence_text=statement.evidence_text, rules_version=rules_version,
        )


# ----------------------------------------------------------------- vogent events
def append_event(
    conn: psycopg.Connection, *, organization_id: str | None, dial_id: str | None,
    event_type: str, payload: dict, rejected_reason: str | None = None,
) -> bool:
    """Append a raw vendor event. Returns False when it is a duplicate delivery."""
    dedupe = hashlib.sha256(
        json.dumps({"t": event_type, "d": dial_id, "p": payload}, sort_keys=True, default=str).encode()
    ).hexdigest()
    row = query_one(
        conn,
        """INSERT INTO vogent_events (organization_id, dial_id, event_type, dedupe_key,
                                      payload, rejected_reason)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (dedupe_key) DO NOTHING
           RETURNING id""",
        (organization_id, dial_id, event_type, dedupe, json.dumps(payload, default=str), rejected_reason),
    )
    return row is not None


# ---------------------------------------------------------------- fault profiles
def register_fault_profile(
    conn: psycopg.Connection, *, dial_id: str, organization_id: str, scenario_id: str,
    scenario_version: int, evaluation_run_id: str | None, true_intent: str | None, profile: dict,
) -> None:
    execute(
        conn,
        """INSERT INTO fault_profiles (dial_id, organization_id, scenario_id, scenario_version,
                                       evaluation_run_id, true_intent, profile)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (dial_id) DO UPDATE
               SET scenario_id = EXCLUDED.scenario_id,
                   scenario_version = EXCLUDED.scenario_version,
                   evaluation_run_id = EXCLUDED.evaluation_run_id,
                   true_intent = EXCLUDED.true_intent,
                   profile = EXCLUDED.profile""",
        (dial_id, organization_id, scenario_id, scenario_version, evaluation_run_id,
         true_intent, json.dumps(profile)),
    )


def get_fault_profile(conn: psycopg.Connection, dial_id: str) -> dict:
    row = query_one(conn, "SELECT profile FROM fault_profiles WHERE dial_id = %s", (dial_id,))
    return dict(row["profile"]) if row else {}


# ----------------------------------------------------------------- staff actions
def insert_staff_action(
    conn: psycopg.Connection, *, call_id: str, organization_id: str, actor: str,
    kind: str, target_callback_id: str | None, note: str | None,
) -> dict:
    return query_one(
        conn,
        """INSERT INTO staff_actions (call_id, organization_id, actor, kind, target_callback_id, note)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (call_id, organization_id, actor, kind, target_callback_id, note),
    )


# -------------------------------------------------------------- evidence bundle
def load_evidence(conn: psycopg.Connection, call_id: str, organization_id: str) -> CallEvidence | None:
    """Assemble everything derivation is allowed to see, scoped to one organization."""
    call_row = get_call(conn, call_id, organization_id)
    if call_row is None:
        return None

    executions = query_all(
        conn,
        """SELECT * FROM action_executions
            WHERE call_id = %s AND organization_id = %s ORDER BY requested_at, id""",
        (call_id, organization_id),
    )
    execution_ids = [str(e["id"]) for e in executions]

    # With no executions there is nothing downstream to look for, and an empty
    # uuid[] parameter would be rejected by PostgreSQL.
    appointments: list[dict] = []
    transfers: list[dict] = []
    callbacks: list[dict] = []
    if execution_ids:
        appointments = query_all(
        conn,
            "SELECT * FROM appointments WHERE organization_id = %s"
            " AND action_execution_id = ANY(%s::uuid[])",
            (organization_id, execution_ids),
        )
        transfers = query_all(
            conn,
            """SELECT * FROM transfer_sessions
                WHERE organization_id = %s AND action_execution_id = ANY(%s::uuid[])
                ORDER BY created_at, attempt_no""",
            (organization_id, execution_ids),
        )
        callbacks = query_all(
            conn,
            "SELECT * FROM callback_requests WHERE organization_id = %s"
            " AND action_execution_id = ANY(%s::uuid[])",
            (organization_id, execution_ids),
        )
    statements = query_all(
        conn,
        """SELECT * FROM agent_statements
            WHERE call_id = %s AND organization_id = %s ORDER BY sequence_no, observed_at""",
        (call_id, organization_id),
    )
    staff = query_all(
        conn,
        "SELECT * FROM staff_actions WHERE call_id = %s AND organization_id = %s ORDER BY created_at",
        (call_id, organization_id),
    )

    return CallEvidence(
        call=CallRecord(
            id=str(call_row["id"]),
            organization_id=str(call_row["organization_id"]),
            lifecycle=Lifecycle(call_row["lifecycle"]),
            agent_classified_intent=(
                Intent(call_row["agent_classified_intent"])
                if call_row["agent_classified_intent"] else None
            ),
        ),
        action_executions=tuple(
            ActionExecution(
                id=str(row["id"]),
                kind=ActionKind(row["kind"]),
                outcome=ActionOutcome(row["outcome"]),
                requested_at=row["requested_at"],
                completed_at=row["completed_at"],
                downstream_ref=row["downstream_ref"],
                duplicate_of_id=str(row["duplicate_of_id"]) if row["duplicate_of_id"] else None,
            )
            for row in executions
        ),
        appointments=tuple(
            Appointment(
                id=str(row["id"]),
                action_execution_id=str(row["action_execution_id"]),
                status=AppointmentStatus(row["status"]),
            )
            for row in appointments
        ),
        transfer_sessions=tuple(
            TransferSession(
                id=str(row["id"]),
                action_execution_id=str(row["action_execution_id"]),
                status=TransferStatus(row["status"]),
                failure_reason=row["failure_reason"],
            )
            for row in transfers
        ),
        callback_requests=tuple(
            CallbackRequest(
                id=str(row["id"]),
                action_execution_id=str(row["action_execution_id"]),
                status=CallbackStatus(row["status"]),
                priority=CallbackPriority(row["priority"]),
            )
            for row in callbacks
        ),
        agent_statements=tuple(
            AgentStatement(
                id=str(row["id"]),
                kind=StatementKind(row["kind"]),
                source=StatementSource(row["source"]),
                observed_at=row["observed_at"],
                sequence_no=row["sequence_no"],
                disposition=Disposition(row["disposition"]) if row["disposition"] else None,
                evidence_text=row["evidence_text"],
            )
            for row in statements
        ),
        staff_actions=tuple(
            StaffAction(
                id=str(row["id"]),
                kind=StaffActionKind(row["kind"]),
                created_at=row["created_at"],
                target_callback_id=(
                    str(row["target_callback_id"]) if row["target_callback_id"] else None
                ),
                actor=row["actor"],
            )
            for row in staff
        ),
    )


def load_evidence_bulk(
    conn: psycopg.Connection, call_ids: list[str], organization_id: str
) -> dict[str, CallEvidence]:
    """Evidence for many calls in a fixed number of queries.

    The attention list needs a derived status for every call. Loading each bundle
    separately turns one page into hundreds of round trips against a hosted
    database, so the rows are fetched once and grouped in memory.
    """
    if not call_ids:
        return {}

    calls = query_all(
        conn, "SELECT * FROM calls WHERE organization_id = %s AND id = ANY(%s::uuid[])",
        (organization_id, call_ids),
    )
    executions = query_all(
        conn,
        """SELECT * FROM action_executions
            WHERE organization_id = %s AND call_id = ANY(%s::uuid[])
            ORDER BY requested_at, id""",
        (organization_id, call_ids),
    )
    statements = query_all(
        conn,
        """SELECT * FROM agent_statements
            WHERE organization_id = %s AND call_id = ANY(%s::uuid[])
            ORDER BY sequence_no, observed_at""",
        (organization_id, call_ids),
    )
    staff = query_all(
        conn,
        """SELECT * FROM staff_actions
            WHERE organization_id = %s AND call_id = ANY(%s::uuid[]) ORDER BY created_at""",
        (organization_id, call_ids),
    )

    execution_ids = [str(e["id"]) for e in executions]
    appointments: list[dict] = []
    transfers: list[dict] = []
    callbacks: list[dict] = []
    if execution_ids:
        appointments = query_all(
            conn,
            "SELECT * FROM appointments WHERE organization_id = %s"
            " AND action_execution_id = ANY(%s::uuid[])",
            (organization_id, execution_ids),
        )
        transfers = query_all(
            conn,
            """SELECT * FROM transfer_sessions
                WHERE organization_id = %s AND action_execution_id = ANY(%s::uuid[])
                ORDER BY created_at, attempt_no""",
            (organization_id, execution_ids),
        )
        callbacks = query_all(
            conn,
            "SELECT * FROM callback_requests WHERE organization_id = %s"
            " AND action_execution_id = ANY(%s::uuid[])",
            (organization_id, execution_ids),
        )

    execution_to_call = {str(e["id"]): str(e["call_id"]) for e in executions}
    grouped: dict[str, dict[str, list]] = {
        str(c["id"]): {"exec": [], "appt": [], "xfer": [], "cb": [], "stmt": [], "staff": []}
        for c in calls
    }
    for row in executions:
        grouped[str(row["call_id"])]["exec"].append(row)
    for key, rows in (("appt", appointments), ("xfer", transfers), ("cb", callbacks)):
        for row in rows:
            call_id = execution_to_call.get(str(row["action_execution_id"]))
            if call_id in grouped:
                grouped[call_id][key].append(row)
    for row in statements:
        grouped[str(row["call_id"])]["stmt"].append(row)
    for row in staff:
        grouped[str(row["call_id"])]["staff"].append(row)

    return {
        str(call["id"]): _build_evidence(call, grouped[str(call["id"])]) for call in calls
    }


def _build_evidence(call_row: dict, parts: dict[str, list]) -> CallEvidence:
    return CallEvidence(
        call=CallRecord(
            id=str(call_row["id"]),
            organization_id=str(call_row["organization_id"]),
            lifecycle=Lifecycle(call_row["lifecycle"]),
            agent_classified_intent=(
                Intent(call_row["agent_classified_intent"])
                if call_row["agent_classified_intent"] else None
            ),
        ),
        action_executions=tuple(_execution(r) for r in parts["exec"]),
        appointments=tuple(
            Appointment(id=str(r["id"]), action_execution_id=str(r["action_execution_id"]),
                        status=AppointmentStatus(r["status"]))
            for r in parts["appt"]
        ),
        transfer_sessions=tuple(
            TransferSession(id=str(r["id"]), action_execution_id=str(r["action_execution_id"]),
                            status=TransferStatus(r["status"]), failure_reason=r["failure_reason"])
            for r in parts["xfer"]
        ),
        callback_requests=tuple(
            CallbackRequest(id=str(r["id"]), action_execution_id=str(r["action_execution_id"]),
                            status=CallbackStatus(r["status"]),
                            priority=CallbackPriority(r["priority"]))
            for r in parts["cb"]
        ),
        agent_statements=tuple(_statement(r) for r in parts["stmt"]),
        staff_actions=tuple(_staff_action(r) for r in parts["staff"]),
    )


def _execution(row: dict) -> ActionExecution:
    return ActionExecution(
        id=str(row["id"]), kind=ActionKind(row["kind"]), outcome=ActionOutcome(row["outcome"]),
        requested_at=row["requested_at"], completed_at=row["completed_at"],
        downstream_ref=row["downstream_ref"],
        duplicate_of_id=str(row["duplicate_of_id"]) if row["duplicate_of_id"] else None,
    )


def _statement(row: dict) -> AgentStatement:
    return AgentStatement(
        id=str(row["id"]), kind=StatementKind(row["kind"]), source=StatementSource(row["source"]),
        observed_at=row["observed_at"], sequence_no=row["sequence_no"],
        disposition=Disposition(row["disposition"]) if row["disposition"] else None,
        evidence_text=row["evidence_text"],
    )


def _staff_action(row: dict) -> StaffAction:
    return StaffAction(
        id=str(row["id"]), kind=StaffActionKind(row["kind"]), created_at=row["created_at"],
        target_callback_id=str(row["target_callback_id"]) if row["target_callback_id"] else None,
        actor=row["actor"],
    )


def raw_evidence_rows(conn: psycopg.Connection, call_id: str, organization_id: str) -> dict[str, Any]:
    """The same rows with their payloads, for the investigation UI and artifacts."""
    executions = query_all(
        conn,
        """SELECT * FROM action_executions WHERE call_id = %s AND organization_id = %s
            ORDER BY requested_at, id""",
        (call_id, organization_id),
    )
    return {"action_executions": executions}
